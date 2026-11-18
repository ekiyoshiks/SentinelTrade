"""Repositórios: consultas ao banco, separadas das regras de negócio e das rotas."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..dominio.carteira import Conta, Posicao
from ..dominio.estados import ESTADOS_ALTERAVEIS, EstadoOrdem
from ..dominio.mercado import Ativo, Cotacao
from ..dominio.ordens import Ordem
from ..dominio.risco import LimiteRisco
from ..dominio.usuarios import CadastroInvestidor, Usuario
from .mapeamento import (MensagemFila, Notificacao, Operacao, OrdemHistorico, RegistroAuditoria,
                         Suspensao)

# Estados cujo valor conta no limite diário de risco (RN03).
_ESTADOS_QUE_CONSOMEM_LIMITE = [
    EstadoOrdem.VALIDADA.value, EstadoOrdem.ENVIADA.value, EstadoOrdem.PARCIALMENTE_EXECUTADA.value,
    EstadoOrdem.EXECUTADA.value, EstadoOrdem.FALHA.value, EstadoOrdem.INTERVENCAO_MANUAL.value,
]


class RepositorioUsuarios:
    def __init__(self, s: Session):
        self.s = s

    def por_login(self, login: str) -> Usuario | None:
        return self.s.scalars(select(Usuario).where(Usuario.login == login)).first()

    def por_id(self, usuario_id: int) -> Usuario | None:
        return self.s.get(Usuario, usuario_id)

    def listar(self) -> list[Usuario]:
        return list(self.s.scalars(select(Usuario).order_by(Usuario.login)))

    def do_investidor(self, investidor_id: int) -> Usuario | None:
        return self.s.scalars(select(Usuario).where(Usuario.investidor_id == investidor_id)).first()


class RepositorioCadastros:
    def __init__(self, s: Session):
        self.s = s

    def investidor(self, investidor_id: int) -> CadastroInvestidor | None:
        return self.s.get(CadastroInvestidor, investidor_id)

    def investidor_por_documento(self, documento: str) -> CadastroInvestidor | None:
        return self.s.scalars(
            select(CadastroInvestidor).where(CadastroInvestidor.documento == documento)).first()

    def investidores(self) -> list[CadastroInvestidor]:
        return list(self.s.scalars(select(CadastroInvestidor).order_by(CadastroInvestidor.nome)))

    def conta_do_investidor(self, investidor_id: int) -> Conta | None:
        return self.s.scalars(select(Conta).where(Conta.investidor_id == investidor_id)).first()

    def conta(self, conta_id: int) -> Conta | None:
        return self.s.get(Conta, conta_id)

    def posicao(self, conta_id: int, ativo_id: int) -> Posicao | None:
        return self.s.scalars(select(Posicao).where(
            Posicao.conta_id == conta_id, Posicao.ativo_id == ativo_id)).first()

    def posicoes_da_conta(self, conta_id: int) -> list[Posicao]:
        return list(self.s.scalars(select(Posicao).where(Posicao.conta_id == conta_id)))

    def limite(self, investidor_id: int) -> LimiteRisco | None:
        return self.s.get(LimiteRisco, investidor_id)

    def limites(self) -> list[LimiteRisco]:
        return list(self.s.scalars(select(LimiteRisco)))


class RepositorioMercado:
    def __init__(self, s: Session):
        self.s = s

    def ativo_por_codigo(self, codigo: str) -> Ativo | None:
        return self.s.scalars(select(Ativo).where(Ativo.codigo == codigo.upper())).first()

    def ativo(self, ativo_id: int) -> Ativo | None:
        return self.s.get(Ativo, ativo_id)

    def ativos(self) -> list[Ativo]:
        return list(self.s.scalars(select(Ativo).order_by(Ativo.codigo)))

    def cotacao(self, ativo_id: int) -> Cotacao | None:
        return self.s.get(Cotacao, ativo_id)

    def cotacoes(self) -> list[Cotacao]:
        return list(self.s.scalars(select(Cotacao)))


class RepositorioOrdens:
    def __init__(self, s: Session):
        self.s = s

    def por_id(self, ordem_id: str) -> Ordem | None:
        return self.s.get(Ordem, ordem_id)

    def por_chave(self, chave: str) -> Ordem | None:
        return self.s.scalars(select(Ordem).where(Ordem.chave_idempotencia == chave)).first()

    def listar(self, *, investidor_id: int | None = None, estado: str | None = None,
               ativo_id: int | None = None, desde: datetime | None = None,
               ate: datetime | None = None, limite: int = 200) -> list[Ordem]:
        consulta = select(Ordem)
        if investidor_id is not None:
            consulta = consulta.where(Ordem.investidor_id == investidor_id)
        if estado:
            consulta = consulta.where(Ordem._estado == estado)
        if ativo_id is not None:
            consulta = consulta.where(Ordem.ativo_id == ativo_id)
        if desde:
            consulta = consulta.where(Ordem.criado_em >= desde)
        if ate:
            consulta = consulta.where(Ordem.criado_em <= ate)
        return list(self.s.scalars(consulta.order_by(Ordem.criado_em.desc()).limit(limite)))

    def total_do_dia(self, investidor_id: int, inicio_dia: datetime,
                     excluir_id: str | None = None) -> Decimal:
        consulta = select(func.coalesce(func.sum(Ordem._valor_estimado), 0)).where(
            Ordem.investidor_id == investidor_id, Ordem.criado_em >= inicio_dia,
            Ordem._estado.in_(_ESTADOS_QUE_CONSOMEM_LIMITE))
        if excluir_id:
            consulta = consulta.where(Ordem.id != excluir_id)
        return Decimal(str(self.s.scalar(consulta) or 0))

    def pendentes_de_reprocessamento(self, agora: datetime) -> list[Ordem]:
        """CSU18: ordens em Falha ou com cancelamento pendente, já na hora de nova tentativa."""
        consulta = select(Ordem).where(
            Ordem._proxima_tentativa_em.is_not(None), Ordem._proxima_tentativa_em <= agora,
            (Ordem._estado == EstadoOrdem.FALHA.value) | (
                Ordem._cancelamento_pendente.is_(True)
                & Ordem._estado.in_([e.value for e in ESTADOS_ALTERAVEIS])))
        return list(self.s.scalars(consulta))

    def contar_por_estado(self) -> dict[str, int]:
        linhas = self.s.execute(select(Ordem._estado, func.count()).group_by(Ordem._estado)).all()
        return {estado: total for estado, total in linhas}

    def historico(self, ordem_id: str) -> list[OrdemHistorico]:
        return list(self.s.scalars(select(OrdemHistorico).where(
            OrdemHistorico.ordem_id == ordem_id).order_by(OrdemHistorico.id)))

    def operacoes(self, ordem_id: str) -> list[Operacao]:
        return list(self.s.scalars(select(Operacao).where(
            Operacao.ordem_id == ordem_id).order_by(Operacao.id)))

    def volume_executado_do_dia(self, inicio_dia: datetime) -> Decimal:
        total = self.s.scalar(select(func.coalesce(func.sum(Operacao.quantidade * Operacao.preco), 0)).where(
            Operacao.executada_em >= inicio_dia))
        return Decimal(str(total or 0))


class RepositorioSuspensoes:
    def __init__(self, s: Session):
        self.s = s

    def ativas(self) -> list[Suspensao]:
        return list(self.s.scalars(select(Suspensao).where(Suspensao.ativa.is_(True))))

    def todas(self, limite: int = 50) -> list[Suspensao]:
        return list(self.s.scalars(select(Suspensao).order_by(Suspensao.id.desc()).limit(limite)))


class RepositorioNotificacoes:
    def __init__(self, s: Session):
        self.s = s

    def do_investidor(self, investidor_id: int, limite: int = 50) -> list[Notificacao]:
        return list(self.s.scalars(select(Notificacao).where(
            Notificacao.investidor_id == investidor_id).order_by(Notificacao.id.desc()).limit(limite)))

    def do_perfil(self, perfil: str, limite: int = 50) -> list[Notificacao]:
        return list(self.s.scalars(select(Notificacao).where(
            Notificacao.destinatario_perfil == perfil).order_by(Notificacao.id.desc()).limit(limite)))

    def pendentes_de_entrega(self) -> int:
        return int(self.s.scalar(select(func.count()).select_from(Notificacao).where(
            Notificacao.entregue.is_(False))) or 0)


class RepositorioFila:
    def __init__(self, s: Session):
        self.s = s

    def resumo(self) -> dict[str, int]:
        linhas = self.s.execute(select(MensagemFila.status, func.count()).group_by(
            MensagemFila.status)).all()
        return {status: total for status, total in linhas}


class RepositorioAuditoria:
    def __init__(self, s: Session):
        self.s = s

    def consultar(self, *, desde: datetime | None = None, ate: datetime | None = None,
                  usuario: str | None = None, acao: str | None = None,
                  entidade_id: str | None = None, limite: int = 500) -> list[RegistroAuditoria]:
        c = select(RegistroAuditoria)
        if desde:
            c = c.where(RegistroAuditoria.ocorrido_em >= desde)
        if ate:
            c = c.where(RegistroAuditoria.ocorrido_em <= ate)
        if usuario:
            c = c.where(RegistroAuditoria.usuario == usuario)
        if acao:
            c = c.where(RegistroAuditoria.acao == acao)
        if entidade_id:
            c = c.where(RegistroAuditoria.entidade_id == entidade_id)
        # ordem cronológica (CSU14, passo 4)
        return list(self.s.scalars(c.order_by(RegistroAuditoria.id).limit(limite)))

    def total(self) -> int:
        return int(self.s.scalar(select(func.count()).select_from(RegistroAuditoria)) or 0)
