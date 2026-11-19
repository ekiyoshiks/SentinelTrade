"""CSU16 — Processar Retorno da Bolsa.

Idempotente: o id do evento é gravado na mesma transação que atualiza ordem, saldo e posição;
uma mensagem repetida é ignorada e nunca debita o saldo duas vezes (RNF-13, RNF-17).
"""
from __future__ import annotations

import logging

from ..dominio.carteira import Posicao
from ..dominio.estados import EstadoOrdem
from ..dominio.excecoes import IntegracaoError, SentinelTradeError
from ..dominio.ordens import Lado
from ..dominio.perfis_notificacao import PERFIL_OPERADOR
from ..dominio.relogio import Relogio
from ..integracoes.interfaces import BolsaGateway, RetornoBolsa, TipoRetorno
from ..persistencia.banco import Banco
from ..persistencia.mapeamento import EventoBolsa, Operacao
from ..persistencia.repositorios import RepositorioCadastros, RepositorioMercado, RepositorioOrdens
from .auditoria import AuditoriaService
from .comum import registrar_historico
from .notificacoes import NotificacaoService

log = logging.getLogger(__name__)

PROCESSADO, DUPLICADO, DESCARTADO, FALHOU = "PROCESSADO", "DUPLICADO", "DESCARTADO", "FALHOU"


class RetornoBolsaService:
    def __init__(self, banco: Banco, relogio: Relogio, bolsa: BolsaGateway, auditoria: AuditoriaService,
                 notificacoes: NotificacaoService):
        self._banco, self._relogio, self._bolsa = banco, relogio, bolsa
        self._auditoria, self._notificacoes = auditoria, notificacoes

    def sincronizar(self) -> dict:
        """Coleta e processa os retornos pendentes da Bolsa."""
        contagem = {PROCESSADO: 0, DUPLICADO: 0, DESCARTADO: 0, FALHOU: 0}
        with self._banco.exclusivo():
            try:
                retornos = self._bolsa.coletar_retornos()
            except IntegracaoError:
                return contagem  # Bolsa indisponível: tentaremos no próximo ciclo
            for retorno in retornos:
                contagem[self.processar(retorno)] += 1
        return contagem

    def processar(self, r: RetornoBolsa) -> str:
        try:
            with self._banco.exclusivo():
                with self._banco.transacao() as s:
                    resultado = self._aplicar(s, r)
        except Exception:  # falha ao gravar: desfaz tudo e mantém a mensagem para nova tentativa
            log.exception("Falha ao processar retorno %s", r.id_evento)
            return FALHOU
        self._bolsa.confirmar_retorno(r.id_evento)
        return resultado

    # ------------------------------------------------------------------
    def _aplicar(self, s, r: RetornoBolsa) -> str:
        agora = self._relogio.agora()
        if s.get(EventoBolsa, r.id_evento) is not None:
            return DUPLICADO  # já processada: ignora sem alterar saldo
        ordens = RepositorioOrdens(s)
        ordem = ordens.por_chave(r.chave)
        valido = r.tipo in {t.value for t in TipoRetorno} and ordem is not None
        if valido and r.tipo in (TipoRetorno.EXECUCAO_TOTAL.value, TipoRetorno.EXECUCAO_PARCIAL.value):
            valido = r.quantidade > 0 and r.preco is not None and r.preco > 0
        if not valido:
            s.add(EventoBolsa(id_evento=r.id_evento, ordem_id=None, tipo=str(r.tipo)[:20], processado_em=agora))
            self._auditoria.registrar(s, usuario="BOLSA", acao="RETORNO_DESCARTADO", resultado="ALERTA",
                                      entidade="evento", entidade_id=r.id_evento,
                                      detalhes={"chave": r.chave, "tipo": r.tipo})
            self._notificacoes.criar(s, tipo="RETORNO_INVALIDO", perfil=PERFIL_OPERADOR,
                                     mensagem=f"Retorno da Bolsa descartado (evento {r.id_evento}).")
            return DESCARTADO

        s.add(EventoBolsa(id_evento=r.id_evento, ordem_id=ordem.id, tipo=r.tipo, processado_em=agora))
        if ordem.finalizada:  # ex.: cancelada localmente; retorno tardio não altera nada
            self._auditoria.registrar(s, usuario="BOLSA", acao="RETORNO_IGNORADO", resultado="ALERTA",
                                      entidade="ordem", entidade_id=ordem.id,
                                      detalhes={"tipo": r.tipo, "estado": ordem.estado.value})
            return DESCARTADO

        anterior = ordem.estado
        if anterior is EstadoOrdem.FALHA:       # a Bolsa claramente conhece a ordem
            ordem.marcar_enviada(agora)
            registrar_historico(s, ordem, anterior.value, EstadoOrdem.ENVIADA.value, agora, "Retorno da Bolsa")
            anterior = EstadoOrdem.ENVIADA

        cadastros, mercado = RepositorioCadastros(s), RepositorioMercado(s)
        conta = cadastros.conta(ordem.conta_id)
        ativo = mercado.ativo(ordem.ativo_id)
        posicao = cadastros.posicao(ordem.conta_id, ordem.ativo_id)

        if r.tipo in (TipoRetorno.EXECUCAO_TOTAL.value, TipoRetorno.EXECUCAO_PARCIAL.value):
            if posicao is None:
                posicao = Posicao(ordem.conta_id, ordem.ativo_id)
                s.add(posicao)
            if ordem.lado is Lado.VENDA and posicao is None:
                raise SentinelTradeError("Posição inexistente para venda.")
            ordem.aplicar_execucao(r.quantidade, r.preco, conta, posicao, agora)
            s.add(Operacao(ordem_id=ordem.id, ativo_id=ordem.ativo_id, quantidade=r.quantidade, preco=r.preco,
                           id_evento_bolsa=r.id_evento, executada_em=agora))
            texto = (f"Ordem {ordem.id} executada: {r.quantidade} {ativo.codigo} a R$ {r.preco}."
                     if ordem.estado is EstadoOrdem.EXECUTADA else
                     f"Ordem {ordem.id} parcialmente executada: {ordem.quantidade_executada}/{ordem.quantidade} "
                     f"{ativo.codigo}.")
            tipo_notif = "ORDEM_EXECUTADA" if ordem.estado is EstadoOrdem.EXECUTADA else "ORDEM_PARCIAL"
        elif r.tipo == TipoRetorno.REJEICAO.value:
            ordem.liberar_reservas(conta, posicao)
            ordem.transitar(EstadoOrdem.REJEITADA, agora, r.motivo or "Rejeitada pela Bolsa.")
            texto, tipo_notif = f"Ordem {ordem.id} rejeitada pela Bolsa: {r.motivo or 'sem detalhe'}.", "ORDEM_REJEITADA"
        else:  # CANCELAMENTO
            ordem.liberar_reservas(conta, posicao)
            ordem.transitar(EstadoOrdem.CANCELADA, agora)
            ordem.marcar_cancelamento_pendente(False, agora)
            texto, tipo_notif = f"Ordem {ordem.id} cancelada.", "ORDEM_CANCELADA"

        registrar_historico(s, ordem, anterior.value, ordem.estado.value, agora, r.motivo,
                            evento="ESTADO" if ordem.estado is not anterior else "EXECUCAO")
        self._notificacoes.criar(s, tipo=tipo_notif, mensagem=texto, investidor_id=ordem.investidor_id,
                                 ordem_id=ordem.id)
        self._auditoria.registrar(s, usuario="BOLSA", acao="RETORNO_PROCESSADO", entidade="ordem",
                                  entidade_id=ordem.id, correlacao_id=ordem.correlacao_id,
                                  detalhes={"evento": r.id_evento, "tipo": r.tipo, "estado": ordem.estado.value,
                                            "quantidade": r.quantidade})
        return PROCESSADO
