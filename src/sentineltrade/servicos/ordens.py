"""CSU04 Enviar · CSU05 Alterar · CSU06 Cancelar · CSU07 Acompanhar · CSU08 Histórico · CSU03 Carteira.

Todo caso de uso roda em uma única transação (tudo ou nada). Recusas e falhas também são
auditadas — em uma segunda transação, já que a primeira é revertida.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from ..config import Configuracoes
from ..dominio.estados import EstadoOrdem
from ..dominio.excecoes import (AcessoNegadoError, BolsaRecusouError, IndisponibilidadeSeguraError,
                                IntegracaoError, IntegracaoTimeoutError, NaoEncontradoError,
                                RegraNegocioError, SentinelTradeError, TransicaoInvalidaError,
                                ValidacaoEntradaError)
from ..dominio.ordens import Lado, Modalidade, Ordem
from ..dominio.relogio import Relogio
from ..dominio.usuarios import Usuario
from ..integracoes.interfaces import BolsaGateway
from ..persistencia.banco import Banco
from ..persistencia.repositorios import (RepositorioCadastros, RepositorioMercado, RepositorioOrdens)
from ..regras.base import ContextoValidacao
from ..regras.calendario import CalendarioPregao, inicio_do_dia_utc
from ..regras.ordem import RN09OrdemAlteravel, ValidadorOrdem
from .auditoria import AuditoriaService
from .comum import ordem_para_dict, registrar_historico
from .fila import BOLSA_ENVIO, FilaMensagens
from .notificacoes import NotificacaoService
from .retorno_bolsa import RetornoBolsaService
from .risco import RiscoService

log = logging.getLogger(__name__)


@dataclass
class DadosNovaOrdem:
    ativo: str
    lado: str
    modalidade: str
    quantidade: int
    preco: Decimal | None = None
    chave_idempotencia: str | None = None


class OrdemService:
    def __init__(self, banco: Banco, relogio: Relogio, config: Configuracoes, auditoria: AuditoriaService,
                 fila: FilaMensagens, notificacoes: NotificacaoService, risco: RiscoService,
                 retorno: RetornoBolsaService, bolsa: BolsaGateway, validador: ValidadorOrdem,
                 calendario: CalendarioPregao):
        self._banco, self._relogio, self._config = banco, relogio, config
        self._auditoria, self._fila, self._notificacoes = auditoria, fila, notificacoes
        self._risco, self._retorno, self._bolsa = risco, retorno, bolsa
        self._validador, self._calendario = validador, calendario

    # ================================================================== helpers
    @staticmethod
    def _exigir(usuario: Usuario, permissao: str) -> None:
        if not usuario.pode(permissao):
            raise AcessoNegadoError("Seu perfil não tem permissão para esta operação.")

    @staticmethod
    def _exigir_investidor(usuario: Usuario) -> int:
        if usuario.investidor_id is None:
            raise AcessoNegadoError("Usuário sem conta de investidor.")
        return usuario.investidor_id

    def _auditar_recusa(self, usuario: Usuario, acao: str, erro: SentinelTradeError, origem: str,
                        entidade_id: str | None = None, detalhes: dict | None = None) -> None:
        """Registra a recusa em transação própria (a do caso de uso foi revertida)."""
        try:
            with self._banco.transacao() as s:
                self._auditoria.registrar(
                    s, usuario=usuario.login, perfil=usuario.perfil.value, acao=acao, entidade="ordem",
                    entidade_id=entidade_id, resultado="RECUSADA", origem=origem,
                    detalhes={"codigo": erro.codigo, "motivo": erro.mensagem, **(detalhes or {})})
        except Exception:  # pragma: no cover
            log.exception("Falha ao auditar recusa")

    def _carregar_do_investidor(self, s, usuario: Usuario, ordem_id: str) -> Ordem:
        """RN13: o investidor só enxerga e opera sobre as próprias ordens."""
        ordem = RepositorioOrdens(s).por_id(ordem_id)
        if ordem is None or ordem.investidor_id != usuario.investidor_id:
            raise NaoEncontradoError("Ordem não encontrada.")
        return ordem

    def _contexto(self, s, ordem: Ordem, excluir_ordem_id: str | None = None) -> ContextoValidacao:
        cadastros, mercado = RepositorioCadastros(s), RepositorioMercado(s)
        agora = self._relogio.agora()
        ativo = mercado.ativo(ordem.ativo_id)
        return ContextoValidacao(
            ordem=ordem, conta=cadastros.conta(ordem.conta_id),
            posicao=cadastros.posicao(ordem.conta_id, ordem.ativo_id), ativo=ativo,
            cotacao=mercado.cotacao(ordem.ativo_id), limite=cadastros.limite(ordem.investidor_id),
            total_dia=RepositorioOrdens(s).total_do_dia(ordem.investidor_id, inicio_do_dia_utc(agora),
                                                        excluir_ordem_id),
            agora=agora, mercado_aberto=self._calendario.esta_aberto(agora),
            proximo_pregao=self._calendario.proximo_horario(agora), config=self._config)

    # ================================================================== CSU04
    def enviar(self, usuario: Usuario, dados: DadosNovaOrdem, origem: str = "API") -> dict:
        self._exigir(usuario, "ordem:enviar")
        investidor_id = self._exigir_investidor(usuario)
        chave = (dados.chave_idempotencia or "").strip() or str(uuid.uuid4())
        if len(chave) > 80:
            raise ValidacaoEntradaError("Chave de idempotência muito longa.")
        with self._banco.exclusivo():
            try:
                return self._enviar(usuario, investidor_id, dados, chave, origem)
            except SentinelTradeError as erro:
                self._auditar_recusa(usuario, "ORDEM_RECUSADA", erro, origem,
                                     detalhes={"ativo": dados.ativo, "lado": dados.lado})
                raise
            except Exception as erro:
                # Falha inesperada na validação: fail-safe (RF-19, RNF-15) — bloqueia novas ordens.
                log.exception("Falha inesperada ao validar ordem")
                self._risco.ativar_automaticamente(f"falha inesperada na validação ({type(erro).__name__})")
                raise IndisponibilidadeSeguraError(
                    "Não foi possível validar a ordem com segurança. Novas ordens foram suspensas.")

    def _enviar(self, usuario: Usuario, investidor_id: int, dados: DadosNovaOrdem, chave: str,
                origem: str) -> dict:
        try:
            lado, modalidade = Lado(dados.lado.upper()), Modalidade(dados.modalidade.upper())
        except ValueError:
            raise ValidacaoEntradaError("Lado deve ser COMPRA/VENDA e modalidade MERCADO/LIMITADA.")
        if dados.preco is not None and dados.preco <= 0:
            raise ValidacaoEntradaError("O preço deve ser maior que zero.", codigo="RN06")
        if modalidade is Modalidade.LIMITADA and dados.preco is None:
            raise ValidacaoEntradaError("Ordem limitada exige preço.", codigo="RN06")

        with self._banco.transacao() as s:
            ordens, cadastros, mercado = RepositorioOrdens(s), RepositorioCadastros(s), RepositorioMercado(s)
            agora = self._relogio.agora()

            existente = ordens.por_chave(chave)       # RN08: mesma chave = mesma ordem
            if existente is not None:
                if existente.investidor_id != investidor_id:
                    raise NaoEncontradoError("Ordem não encontrada.")
                self._auditoria.registrar(
                    s, usuario=usuario.login, perfil=usuario.perfil.value, acao="ORDEM_DUPLICADA_IGNORADA",
                    entidade="ordem", entidade_id=existente.id, origem=origem,
                    correlacao_id=existente.correlacao_id, detalhes={"chave": chave})
                ativo = mercado.ativo(existente.ativo_id)
                return ordem_para_dict(existente, ativo.codigo, duplicada=True)

            investidor = cadastros.investidor(investidor_id)
            if investidor is None or not investidor.ativo:        # defesa em profundidade além da sessão
                raise AcessoNegadoError("Cadastro de investidor inativo.")

            ativo = mercado.ativo_por_codigo(dados.ativo or "")
            if ativo is None:
                raise ValidacaoEntradaError("Ativo não encontrado.")
            suspensao = self._risco.suspensao_ativa(s, ativo.codigo)
            if suspensao is not None:
                raise IndisponibilidadeSeguraError(
                    "Novas ordens estão temporariamente suspensas. Consultas e cancelamentos continuam disponíveis.",
                    detalhes={"escopo": suspensao.escopo})

            conta = cadastros.conta_do_investidor(investidor_id)
            if conta is None:
                raise NaoEncontradoError("Conta não encontrada.")
            ordem = Ordem.nova(
                modalidade, id=f"ORD-{uuid.uuid4().hex[:10].upper()}", chave_idempotencia=chave,
                investidor_id=investidor_id, conta_id=conta.id, ativo_id=ativo.id, lado=lado,
                quantidade=dados.quantidade, preco_limite=dados.preco, agora=agora,
                correlacao_id=str(uuid.uuid4()))
            cotacao = mercado.cotacao(ativo.id)
            ordem.definir_valuacao(ordem.preco_unitario_estimado(
                cotacao.preco if cotacao else None, self._config.margem_reserva_mercado))

            contexto = self._contexto(s, ordem)
            try:
                self._validador.validar(contexto)
            except RegraNegocioError as erro:
                if not erro.rejeita_ordem:
                    raise          # lote/preço/cotação: volta ao passo 1, sem criar ordem
                ordem.transitar(EstadoOrdem.REJEITADA, agora, erro.mensagem)
                s.add(ordem)
                registrar_historico(s, ordem, None, EstadoOrdem.CRIADA.value, agora)
                registrar_historico(s, ordem, EstadoOrdem.CRIADA.value, EstadoOrdem.REJEITADA.value, agora,
                                    erro.mensagem)
                self._notificacoes.criar(s, tipo="ORDEM_REJEITADA", investidor_id=investidor_id,
                                         ordem_id=ordem.id, mensagem=f"Ordem {ordem.id} rejeitada: {erro.mensagem}")
                self._auditoria.registrar(
                    s, usuario=usuario.login, perfil=usuario.perfil.value, acao="ORDEM_REJEITADA",
                    entidade="ordem", entidade_id=ordem.id, resultado="RECUSADA", origem=origem,
                    correlacao_id=ordem.correlacao_id, detalhes={"regra": erro.codigo, "motivo": erro.mensagem})
                return ordem_para_dict(ordem, ativo.codigo)

            ordem.reservar(contexto.conta, contexto.posicao)
            ordem.transitar(EstadoOrdem.VALIDADA, agora)
            s.add(ordem)
            registrar_historico(s, ordem, None, EstadoOrdem.CRIADA.value, agora)
            registrar_historico(s, ordem, EstadoOrdem.CRIADA.value, EstadoOrdem.VALIDADA.value, agora)
            self._fila.publicar(s, BOLSA_ENVIO, {"ordem_id": ordem.id})
            self._auditoria.registrar(
                s, usuario=usuario.login, perfil=usuario.perfil.value, acao="ORDEM_ACEITA", entidade="ordem",
                entidade_id=ordem.id, origem=origem, correlacao_id=ordem.correlacao_id,
                detalhes={"ativo": ativo.codigo, "lado": lado.value, "modalidade": modalidade.value,
                          "quantidade": dados.quantidade, "valor_estimado": str(ordem.valor_estimado)})
            return ordem_para_dict(ordem, ativo.codigo)

    # ================================================================== CSU05
    def alterar(self, usuario: Usuario, ordem_id: str, quantidade: int | None = None,
                preco: Decimal | None = None, origem: str = "API") -> dict:
        self._exigir(usuario, "ordem:alterar")
        self._exigir_investidor(usuario)
        with self._banco.exclusivo():
            self._retorno.sincronizar()    # traz execuções que ocorreram antes da alteração
            try:
                with self._banco.transacao() as s:
                    ordem = self._carregar_do_investidor(s, usuario, ordem_id)
                    if not ordem.alteravel:
                        raise TransicaoInvalidaError(
                            f"Ordem {ordem.estado.value} não pode ser alterada (RN09).")
                    mercado = RepositorioMercado(s)
                    ativo = mercado.ativo(ordem.ativo_id)
                    if preco is not None and ordem.modalidade is Modalidade.MERCADO:
                        raise ValidacaoEntradaError("Ordem a mercado não possui preço para alterar.")
                    if quantidade is None and preco is None:
                        raise ValidacaoEntradaError("Informe nova quantidade e/ou novo preço.")
                    agora = self._relogio.agora()
                    nova_qtd = quantidade if quantidade is not None else ordem.quantidade
                    contexto = self._contexto(s, ordem, excluir_ordem_id=ordem.id)

                    ordem.liberar_reservas(contexto.conta, contexto.posicao)
                    novo_limite = preco if preco is not None else ordem.preco_limite
                    cotacao = contexto.cotacao
                    unitario = (novo_limite if ordem.modalidade is Modalidade.LIMITADA else
                                ordem.preco_unitario_estimado(cotacao.preco if cotacao else None,
                                                              self._config.margem_reserva_mercado))
                    ordem.modificar(nova_qtd, preco, unitario, agora)
                    self._validador.validar(contexto)      # revalida com os novos dados
                    ordem.reservar(contexto.conta, contexto.posicao)

                    if ordem.estado is not EstadoOrdem.VALIDADA:   # a Bolsa já conhece a ordem
                        try:
                            self._bolsa.alterar(ordem.chave_idempotencia, ordem.quantidade, ordem.preco_limite)
                        except IntegracaoError as erro:
                            if isinstance(erro, BolsaRecusouError):
                                raise
                            raise IntegracaoTimeoutError(
                                "A Bolsa não respondeu; a alteração não foi aplicada.") from erro
                    registrar_historico(s, ordem, ordem.estado.value, ordem.estado.value, agora,
                                        f"qtd={ordem.quantidade} preço={ordem.preco_limite}", evento="ALTERACAO")
                    self._auditoria.registrar(
                        s, usuario=usuario.login, perfil=usuario.perfil.value, acao="ORDEM_ALTERADA",
                        entidade="ordem", entidade_id=ordem.id, origem=origem, correlacao_id=ordem.correlacao_id,
                        detalhes={"quantidade": ordem.quantidade, "preco": str(ordem.preco_limite),
                                  "versao": ordem.versao})
                    return ordem_para_dict(ordem, ativo.codigo)
            except SentinelTradeError as erro:
                self._auditar_recusa(usuario, "ORDEM_ALTERACAO_RECUSADA", erro, origem, ordem_id)
                raise

    # ================================================================== CSU06
    def cancelar(self, usuario: Usuario, ordem_id: str, origem: str = "API") -> dict:
        self._exigir(usuario, "ordem:cancelar")
        self._exigir_investidor(usuario)
        with self._banco.exclusivo():
            self._retorno.sincronizar()
            try:
                with self._banco.transacao() as s:
                    ordem = self._carregar_do_investidor(s, usuario, ordem_id)
                    ctx = self._contexto(s, ordem)
                    RN09OrdemAlteravel().validar(ctx)
                    agora = self._relogio.agora()
                    anterior = ordem.estado
                    ativo = ctx.ativo
                    parcial = ordem.quantidade_executada

                    if anterior is not EstadoOrdem.VALIDADA:      # a Bolsa já conhece a ordem
                        try:
                            self._bolsa.cancelar(ordem.chave_idempotencia)
                        except IntegracaoTimeoutError:
                            espera = self._config.reprocessamento_espera_base_s
                            ordem.marcar_cancelamento_pendente(True, agora)
                            ordem.registrar_tentativa(agora, agora + timedelta(seconds=espera))
                            self._notificacoes.criar(
                                s, tipo="CANCELAMENTO_PENDENTE", investidor_id=ordem.investidor_id,
                                ordem_id=ordem.id,
                                mensagem=f"Cancelamento da ordem {ordem.id} pendente; a ordem segue ativa até a confirmação.")
                            self._auditoria.registrar(
                                s, usuario=usuario.login, perfil=usuario.perfil.value, acao="ORDEM_CANCELAMENTO_PENDENTE",
                                entidade="ordem", entidade_id=ordem.id, resultado="PENDENTE", origem=origem,
                                correlacao_id=ordem.correlacao_id)
                            return ordem_para_dict(ordem, ativo.codigo, aviso="Cancelamento pendente: Bolsa sem resposta.")
                    else:
                        self._fila.cancelar_por_ordem(s, BOLSA_ENVIO, ordem.id)

                    ordem.liberar_reservas(ctx.conta, ctx.posicao)
                    ordem.transitar(EstadoOrdem.CANCELADA, agora)
                    ordem.marcar_cancelamento_pendente(False, agora)
                    registrar_historico(s, ordem, anterior.value, EstadoOrdem.CANCELADA.value, agora,
                                        "Cancelada pelo investidor")
                    self._notificacoes.criar(
                        s, tipo="ORDEM_CANCELADA", investidor_id=ordem.investidor_id, ordem_id=ordem.id,
                        mensagem=f"Ordem {ordem.id} cancelada" + (f" (executado: {parcial})." if parcial else "."))
                    self._auditoria.registrar(
                        s, usuario=usuario.login, perfil=usuario.perfil.value, acao="ORDEM_CANCELADA",
                        entidade="ordem", entidade_id=ordem.id, origem=origem, correlacao_id=ordem.correlacao_id,
                        detalhes={"quantidade_executada": parcial})
                    return ordem_para_dict(ordem, ativo.codigo)
            except SentinelTradeError as erro:
                self._auditar_recusa(usuario, "ORDEM_CANCELAMENTO_RECUSADO", erro, origem, ordem_id)
                raise

    # ================================================================== CSU07 / CSU08 / CSU03
    def obter(self, usuario: Usuario, ordem_id: str) -> dict:
        """CSU07: estado atual, quantidade executada e histórico de eventos."""
        self._exigir(usuario, "ordem:ver")
        with self._banco.transacao() as s:
            ordem = self._carregar_do_investidor(s, usuario, ordem_id)
            repo = RepositorioOrdens(s)
            ativo = RepositorioMercado(s).ativo(ordem.ativo_id)
            return ordem_para_dict(
                ordem, ativo.codigo,
                historico=[{"evento": h.evento, "de": h.estado_anterior, "para": h.estado_novo,
                            "motivo": h.motivo, "em": h.criado_em.isoformat()} for h in repo.historico(ordem.id)],
                operacoes=[{"quantidade": o.quantidade, "preco": str(o.preco), "em": o.executada_em.isoformat()}
                           for o in repo.operacoes(ordem.id)])

    def listar(self, usuario: Usuario, *, estado: str | None = None, ativo: str | None = None,
               desde: datetime | None = None, ate: datetime | None = None, limite: int = 200) -> list[dict]:
        """CSU08: histórico filtrado por período, ativo e status. Operadores/auditor veem todas."""
        todas = usuario.pode("ordem:ver_todas")
        if not todas:
            self._exigir(usuario, "historico:ver")
        with self._banco.transacao() as s:
            mercado = RepositorioMercado(s)
            ativo_id = None
            if ativo:
                a = mercado.ativo_por_codigo(ativo)
                if a is None:
                    return []
                ativo_id = a.id
            codigos = {a.id: a.codigo for a in mercado.ativos()}
            ordens = RepositorioOrdens(s).listar(
                investidor_id=None if todas else usuario.investidor_id, estado=estado or None,
                ativo_id=ativo_id, desde=desde, ate=ate, limite=min(limite, 1000))
            return [ordem_para_dict(o, codigos.get(o.ativo_id, "?")) for o in ordens]

    def carteira(self, usuario: Usuario) -> dict:
        """CSU03: saldo, posições, preço médio e resultado."""
        self._exigir(usuario, "carteira:ver")
        investidor_id = self._exigir_investidor(usuario)
        with self._banco.transacao() as s:
            cadastros, mercado = RepositorioCadastros(s), RepositorioMercado(s)
            conta = cadastros.conta_do_investidor(investidor_id)
            if conta is None:
                raise NaoEncontradoError("Conta não encontrada.")
            posicoes = []
            valor_total = Decimal("0")
            for p in cadastros.posicoes_da_conta(conta.id):
                if p.quantidade == 0:
                    continue
                ativo = mercado.ativo(p.ativo_id)
                cot = mercado.cotacao(p.ativo_id)
                preco = cot.preco if cot else p.preco_medio
                valor = preco * p.quantidade
                valor_total += valor
                posicoes.append({
                    "ativo": ativo.codigo, "quantidade": p.quantidade, "reservada": p.reservada,
                    "disponivel": p.disponivel, "preco_medio": str(p.preco_medio), "preco_atual": str(preco),
                    "valor_atual": f"{valor:.2f}", "resultado": str(p.resultado(preco))})
            return {"saldo": str(conta.saldo), "reservado": str(conta.reservado),
                    "disponivel": str(conta.disponivel), "posicoes": posicoes,
                    "valor_posicoes": f"{valor_total:.2f}",
                    "patrimonio": f"{conta.saldo + valor_total:.2f}",
                    "resultado_total": f"{sum((Decimal(x['resultado']) for x in posicoes), Decimal('0')):.2f}"}
