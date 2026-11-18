"""Mapeamento objeto-relacional *imperativo*.

As classes de domínio continuam Python puro (sem herdar de modelos do ORM). Aqui apenas
dizemos qual coluna guarda cada atributo — inclusive os atributos privados (``_saldo``),
o que preserva o encapsulamento. Registros técnicos (auditoria, fila…) também são mapeados.
"""
from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.orm import registry

from ..dominio.carteira import Conta, Posicao
from ..dominio.excecoes import RegraNegocioError
from ..dominio.mercado import Ativo, Cotacao
from ..dominio.ordens import Ordem, OrdemLimitada, OrdemMercado
from ..dominio.risco import LimiteRisco
from ..dominio.usuarios import (CadastroInvestidor, Usuario, UsuarioAdministrador, UsuarioAuditor,
                                UsuarioInvestidor, UsuarioOperadorRisco)
from . import tabelas as t


class Registro:
    """Base simples para registros técnicos: aceita campos por palavra-chave."""

    def __init__(self, **campos):
        for chave, valor in campos.items():
            setattr(self, chave, valor)


class DesafioMfa(Registro): ...
class OrdemHistorico(Registro): ...
class Operacao(Registro): ...
class EventoBolsa(Registro): ...
class Notificacao(Registro): ...
class MensagemFila(Registro): ...
class RegistroAuditoria(Registro): ...
class Suspensao(Registro): ...


_reg = registry()
_mapeado = False


def mapear() -> None:
    """Executa o mapeamento uma única vez por processo."""
    global _mapeado
    if _mapeado:
        return
    _mapeado = True

    _reg.map_imperatively(CadastroInvestidor, t.investidores, properties={"_ativo": t.investidores.c.ativo})

    usuario_m = _reg.map_imperatively(
        Usuario, t.usuarios, polymorphic_on=t.usuarios.c.perfil, polymorphic_identity=None,
        properties={
            "_senha_hash": t.usuarios.c.senha_hash, "_ativo": t.usuarios.c.ativo,
            "_tentativas_falhas": t.usuarios.c.tentativas_falhas,
            "_bloqueado_ate": t.usuarios.c.bloqueado_ate,
            "_perfil": t.usuarios.c.perfil,
        })
    for classe in (UsuarioInvestidor, UsuarioOperadorRisco, UsuarioAdministrador, UsuarioAuditor):
        _reg.map_imperatively(classe, inherits=usuario_m, polymorphic_identity=classe.PERFIL.value)

    _reg.map_imperatively(Conta, t.contas, properties={
        "_saldo": t.contas.c.saldo, "_reservado": t.contas.c.reservado})

    _reg.map_imperatively(Ativo, t.ativos, properties={
        "_tipo": t.ativos.c.tipo, "_lote_padrao": t.ativos.c.lote_padrao,
        "_situacao": t.ativos.c.situacao})

    _reg.map_imperatively(Posicao, t.posicoes, properties={
        "_quantidade": t.posicoes.c.quantidade, "_reservada": t.posicoes.c.reservada,
        "_preco_medio": t.posicoes.c.preco_medio})

    _reg.map_imperatively(Cotacao, t.cotacoes, properties={
        "_preco": t.cotacoes.c.preco, "_volume": t.cotacoes.c.volume,
        "_variacao": t.cotacoes.c.variacao, "_atualizada_em": t.cotacoes.c.atualizada_em})

    _reg.map_imperatively(LimiteRisco, t.limites_risco, properties={
        "_max_por_ordem": t.limites_risco.c.max_por_ordem, "_max_diario": t.limites_risco.c.max_diario})

    o = t.ordens
    ordem_m = _reg.map_imperatively(
        Ordem, o, polymorphic_on=o.c.modalidade, polymorphic_identity=None,
        properties={
            "_modalidade": o.c.modalidade, "_lado": o.c.lado, "_quantidade": o.c.quantidade,
            "_quantidade_executada": o.c.quantidade_executada, "_preco_limite": o.c.preco_limite,
            "_preco_reserva": o.c.preco_reserva, "_valor_estimado": o.c.valor_estimado,
            "_valor_reservado": o.c.valor_reservado, "_quantidade_reservada": o.c.quantidade_reservada,
            "_preco_medio_execucao": o.c.preco_medio_execucao, "_estado": o.c.estado,
            "_tentativas": o.c.tentativas, "_proxima_tentativa_em": o.c.proxima_tentativa_em,
            "_cancelamento_pendente": o.c.cancelamento_pendente,
            "_motivo_rejeicao": o.c.motivo_rejeicao, "_versao": o.c.versao,
        })
    _reg.map_imperatively(OrdemMercado, inherits=ordem_m, polymorphic_identity="MERCADO")
    _reg.map_imperatively(OrdemLimitada, inherits=ordem_m, polymorphic_identity="LIMITADA")

    _reg.map_imperatively(DesafioMfa, t.desafios_mfa)
    _reg.map_imperatively(OrdemHistorico, t.ordens_historico)
    _reg.map_imperatively(Operacao, t.operacoes)
    _reg.map_imperatively(EventoBolsa, t.eventos_bolsa)
    _reg.map_imperatively(Notificacao, t.notificacoes)
    _reg.map_imperatively(MensagemFila, t.fila_mensagens)
    _reg.map_imperatively(RegistroAuditoria, t.auditoria)
    _reg.map_imperatively(Suspensao, t.suspensoes)

    # RN12: nenhum perfil altera ou exclui registros de auditoria (defesa em profundidade:
    # além deste guarda no ORM, o banco possui triggers — ver Banco.criar_tabelas).
    def _bloquear(*_args):
        raise RegraNegocioError("Registros de auditoria são imutáveis.", codigo="RN12")

    event.listen(RegistroAuditoria, "before_update", _bloquear)
    event.listen(RegistroAuditoria, "before_delete", _bloquear)


mapear()
