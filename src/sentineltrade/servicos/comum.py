"""Funções compartilhadas pelos serviços de ordem."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ..dominio.mercado import Ativo
from ..dominio.ordens import Ordem
from ..integracoes.interfaces import PedidoBolsa
from ..persistencia.mapeamento import OrdemHistorico


def registrar_historico(s: Session, ordem: Ordem, anterior: str | None, novo: str, agora: datetime,
                        motivo: str | None = None, evento: str = "ESTADO") -> None:
    s.add(OrdemHistorico(ordem_id=ordem.id, evento=evento, estado_anterior=anterior, estado_novo=novo,
                         motivo=(motivo or None) and motivo[:300], criado_em=agora))


def pedido_bolsa(ordem: Ordem, ativo: Ativo) -> PedidoBolsa:
    return PedidoBolsa(chave=ordem.chave_idempotencia, codigo_ativo=ativo.codigo, lado=ordem.lado.value,
                       modalidade=ordem.modalidade.value, quantidade=ordem.quantidade,
                       preco_limite=ordem.preco_limite, lote=ativo.lote_padrao)


def ordem_para_dict(ordem: Ordem, codigo_ativo: str, **extra) -> dict:
    return {
        "id": ordem.id, "chave_idempotencia": ordem.chave_idempotencia, "ativo": codigo_ativo,
        "lado": ordem.lado.value, "modalidade": ordem.modalidade.value, "quantidade": ordem.quantidade,
        "quantidade_executada": ordem.quantidade_executada,
        "preco_limite": str(ordem.preco_limite) if ordem.preco_limite is not None else None,
        "preco_medio_execucao": str(ordem.preco_medio_execucao) if ordem.quantidade_executada else None,
        "valor_estimado": str(ordem.valor_estimado), "estado": ordem.estado.value,
        "motivo_rejeicao": ordem.motivo_rejeicao, "tentativas": ordem.tentativas,
        "cancelamento_pendente": ordem.cancelamento_pendente, "investidor_id": ordem.investidor_id,
        "correlacao_id": ordem.correlacao_id, "criado_em": ordem.criado_em.isoformat(),
        "atualizado_em": ordem.atualizado_em.isoformat(), "versao": ordem.versao, **extra,
    }
