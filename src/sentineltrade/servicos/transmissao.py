"""Transmissão assíncrona à Bolsa (fila) e CSU18 — Reprocessar Ordens Pendentes.

Time-out da Bolsa → ordem em Falha → o reprocessamento consulta a Bolsa antes de reenviar e
reenvia sempre com a *mesma chave de idempotência*, evitando ordem duplicada (RNF-12, RNF-13).
"""
from __future__ import annotations

import logging
from datetime import timedelta

from ..config import Configuracoes
from ..dominio.estados import ESTADOS_ALTERAVEIS, EstadoOrdem
from ..dominio.excecoes import BolsaRecusouError, IntegracaoError, IntegracaoTimeoutError
from ..dominio.perfis_notificacao import PERFIL_OPERADOR
from ..dominio.relogio import Relogio
from ..integracoes.interfaces import BolsaGateway
from ..persistencia.banco import Banco
from ..persistencia.mapeamento import MensagemFila
from ..persistencia.repositorios import RepositorioCadastros, RepositorioMercado, RepositorioOrdens
from .auditoria import AuditoriaService
from .comum import pedido_bolsa, registrar_historico
from .fila import BOLSA_ENVIO, FilaMensagens
from .notificacoes import NotificacaoService

log = logging.getLogger(__name__)


class TransmissaoBolsaService:
    def __init__(self, banco: Banco, relogio: Relogio, config: Configuracoes, bolsa: BolsaGateway,
                 fila: FilaMensagens, auditoria: AuditoriaService, notificacoes: NotificacaoService):
        self._banco, self._relogio, self._config, self._bolsa = banco, relogio, config, bolsa
        self._fila, self._auditoria, self._notificacoes = fila, auditoria, notificacoes

    def _proxima(self, tentativas: int):
        espera = self._config.reprocessamento_espera_base_s * (2 ** max(0, tentativas - 1))
        return self._relogio.agora() + timedelta(seconds=espera)

    # ------------------------------------------------------------------ envio (fila)
    def processar_envios(self, limite: int = 50) -> int:
        enviados = 0
        with self._banco.exclusivo():
            with self._banco.transacao() as s:
                ids = [m.id for m in self._fila.proximas(s, BOLSA_ENVIO, limite)]
            for msg_id in ids:
                try:
                    with self._banco.transacao() as s:
                        enviados += self._enviar_uma(s, msg_id)
                except Exception as erro:   # erro inesperado: nova tentativa / fila morta
                    log.exception("Falha ao transmitir mensagem %s", msg_id)
                    with self._banco.transacao() as s:
                        msg = s.get(MensagemFila, msg_id)
                        self._fila.falhar(msg, f"{type(erro).__name__}: {erro}")
        return enviados

    def _enviar_uma(self, s, msg_id: int) -> int:
        msg = s.get(MensagemFila, msg_id)
        ordens = RepositorioOrdens(s)
        ordem = ordens.por_id(self._fila.dados(msg)["ordem_id"])
        if ordem is None or ordem.estado is not EstadoOrdem.VALIDADA:
            self._fila.concluir(msg)       # cancelada ou já tratada
            return 0
        agora = self._relogio.agora()
        ativo = RepositorioMercado(s).ativo(ordem.ativo_id)
        ordem.marcar_enviada(agora)
        registrar_historico(s, ordem, EstadoOrdem.VALIDADA.value, EstadoOrdem.ENVIADA.value, agora,
                            "Transmitida à Bolsa")
        try:
            resposta = self._bolsa.enviar(pedido_bolsa(ordem, ativo))
        except IntegracaoError as erro:
            ordem.marcar_falha(agora, None)
            ordem.registrar_tentativa(agora, self._proxima(1))
            registrar_historico(s, ordem, EstadoOrdem.ENVIADA.value, EstadoOrdem.FALHA.value, agora, erro.mensagem)
            self._fila.concluir(msg)        # a partir daqui, o CSU18 assume
            self._notificacoes.criar(
                s, tipo="ORDEM_PENDENTE", investidor_id=ordem.investidor_id, ordem_id=ordem.id,
                mensagem=f"Ordem {ordem.id}: situação pendente (Bolsa sem resposta). Tentaremos novamente.")
            self._auditoria.registrar(s, usuario="SISTEMA", acao="ORDEM_FALHA_ENVIO", resultado="FALHA",
                                      entidade="ordem", entidade_id=ordem.id, correlacao_id=ordem.correlacao_id,
                                      detalhes={"motivo": erro.mensagem})
            return 0
        ordem.id_bolsa = resposta.id_bolsa
        self._fila.concluir(msg)
        self._auditoria.registrar(s, usuario="SISTEMA", acao="ORDEM_ENVIADA_BOLSA", entidade="ordem",
                                  entidade_id=ordem.id, correlacao_id=ordem.correlacao_id,
                                  detalhes={"id_bolsa": resposta.id_bolsa})
        return 1

    # ------------------------------------------------------------------ CSU18
    def reprocessar_pendentes(self) -> dict:
        resumo = {"reenviadas": 0, "recuperadas": 0, "ainda_pendentes": 0, "intervencao_manual": 0,
                  "cancelamentos_concluidos": 0}
        with self._banco.exclusivo():
            with self._banco.transacao() as s:
                ids = [o.id for o in RepositorioOrdens(s).pendentes_de_reprocessamento(self._relogio.agora())]
            for ordem_id in ids:
                try:
                    with self._banco.transacao() as s:
                        self._reprocessar(s, ordem_id, resumo)
                except Exception:
                    log.exception("Falha ao reprocessar ordem %s", ordem_id)
        return resumo

    def _intervencao_manual(self, s, ordem, agora, resumo: dict, motivo: str) -> None:
        anterior = ordem.estado
        ordem.transitar(EstadoOrdem.INTERVENCAO_MANUAL, agora)
        ordem.encerrar_tentativas(agora)
        registrar_historico(s, ordem, anterior.value, EstadoOrdem.INTERVENCAO_MANUAL.value, agora, motivo)
        self._notificacoes.criar(s, tipo="INTERVENCAO_MANUAL", investidor_id=ordem.investidor_id,
                                 ordem_id=ordem.id,
                                 mensagem=f"Ordem {ordem.id} encaminhada para intervenção manual.")
        self._notificacoes.criar(s, tipo="INTERVENCAO_MANUAL", perfil=PERFIL_OPERADOR, ordem_id=ordem.id,
                                 mensagem=f"Ordem {ordem.id} atingiu o limite de tentativas e exige intervenção manual.")
        self._auditoria.registrar(s, usuario="SISTEMA", acao="ORDEM_INTERVENCAO_MANUAL", resultado="ALERTA",
                                  entidade="ordem", entidade_id=ordem.id, correlacao_id=ordem.correlacao_id,
                                  detalhes={"tentativas": ordem.tentativas})
        resumo["intervencao_manual"] += 1

    def _reprocessar(self, s, ordem_id: str, resumo: dict) -> None:
        ordem = RepositorioOrdens(s).por_id(ordem_id)
        if ordem is None:
            return
        agora = self._relogio.agora()
        maximo = self._config.bolsa_max_tentativas
        ativo = RepositorioMercado(s).ativo(ordem.ativo_id)

        if ordem.estado is EstadoOrdem.FALHA:
            if ordem.tentativas >= maximo:
                self._intervencao_manual(s, ordem, agora, resumo, "Limite de tentativas atingido")
                return
            try:
                status = self._bolsa.consultar(ordem.chave_idempotencia)    # a Bolsa já recebeu?
                if status is None:
                    resposta = self._bolsa.enviar(pedido_bolsa(ordem, ativo))  # mesma chave de idempotência
                    id_bolsa = resposta.id_bolsa
                    resumo["reenviadas"] += 1
                else:
                    id_bolsa = status.id_bolsa
                    resumo["recuperadas"] += 1
            except IntegracaoError as erro:
                ordem.registrar_tentativa(agora, self._proxima(ordem.tentativas + 1))
                resumo["ainda_pendentes"] += 1
                self._auditoria.registrar(s, usuario="SISTEMA", acao="ORDEM_REPROCESSAMENTO", resultado="FALHA",
                                          entidade="ordem", entidade_id=ordem.id, correlacao_id=ordem.correlacao_id,
                                          detalhes={"tentativa": ordem.tentativas, "motivo": erro.mensagem})
                if ordem.tentativas >= maximo:
                    self._intervencao_manual(s, ordem, agora, resumo, "Limite de tentativas atingido")
                return
            ordem.marcar_enviada(agora, id_bolsa)
            registrar_historico(s, ordem, EstadoOrdem.FALHA.value, EstadoOrdem.ENVIADA.value, agora,
                                "Reprocessamento (CSU18)")
            self._auditoria.registrar(s, usuario="SISTEMA", acao="ORDEM_REPROCESSADA", entidade="ordem",
                                      entidade_id=ordem.id, correlacao_id=ordem.correlacao_id,
                                      detalhes={"id_bolsa": id_bolsa})
            return

        if ordem.cancelamento_pendente and ordem.estado in ESTADOS_ALTERAVEIS:
            cadastros = RepositorioCadastros(s)
            try:
                self._bolsa.cancelar(ordem.chave_idempotencia)
            except IntegracaoTimeoutError:
                ordem.registrar_tentativa(agora, self._proxima(ordem.tentativas + 1)
                                          if ordem.tentativas < maximo else None)
                if ordem.tentativas >= maximo:
                    self._notificacoes.criar(
                        s, tipo="CANCELAMENTO_FALHOU", perfil=PERFIL_OPERADOR, ordem_id=ordem.id,
                        mensagem=f"Cancelamento da ordem {ordem.id} não confirmado após {maximo} tentativas.")
                resumo["ainda_pendentes"] += 1
                return
            except BolsaRecusouError:
                ordem.marcar_cancelamento_pendente(False, agora)   # foi executada antes do cancelamento
                ordem.encerrar_tentativas(agora)
                return
            anterior = ordem.estado
            ordem.liberar_reservas(cadastros.conta(ordem.conta_id), cadastros.posicao(ordem.conta_id, ordem.ativo_id))
            ordem.transitar(EstadoOrdem.CANCELADA, agora)
            ordem.marcar_cancelamento_pendente(False, agora)
            ordem.encerrar_tentativas(agora)
            registrar_historico(s, ordem, anterior.value, EstadoOrdem.CANCELADA.value, agora,
                                "Cancelamento confirmado (CSU18)")
            self._notificacoes.criar(s, tipo="ORDEM_CANCELADA", investidor_id=ordem.investidor_id,
                                     ordem_id=ordem.id, mensagem=f"Ordem {ordem.id} cancelada.")
            self._auditoria.registrar(s, usuario="SISTEMA", acao="ORDEM_CANCELADA", entidade="ordem",
                                      entidade_id=ordem.id, correlacao_id=ordem.correlacao_id,
                                      detalhes={"origem": "reprocessamento"})
            resumo["cancelamentos_concluidos"] += 1
