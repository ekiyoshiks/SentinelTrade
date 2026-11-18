"""Ativos negociáveis e cotações."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum

from .dinheiro import q2


class TipoAtivo(str, Enum):
    ACAO = "ACAO"
    ETF = "ETF"
    FII = "FII"


class SituacaoAtivo(str, Enum):
    NEGOCIAVEL = "NEGOCIAVEL"
    SUSPENSO = "SUSPENSO"


class Ativo:
    def __init__(self, codigo: str, nome: str, tipo: TipoAtivo, lote_padrao: int = 100):
        self.codigo = codigo.upper()
        self.nome = nome
        self._tipo = tipo.value
        self._lote_padrao = lote_padrao
        self._situacao = SituacaoAtivo.NEGOCIAVEL.value

    @property
    def tipo(self) -> TipoAtivo:
        return TipoAtivo(self._tipo)

    @property
    def lote_padrao(self) -> int:
        return self._lote_padrao

    @property
    def situacao(self) -> SituacaoAtivo:
        return SituacaoAtivo(self._situacao)

    @property
    def negociavel(self) -> bool:
        return self.situacao is SituacaoAtivo.NEGOCIAVEL

    def quantidade_valida(self, quantidade: int) -> bool:
        """RN05: a quantidade deve ser múltipla do lote padrão."""
        return quantidade > 0 and quantidade % self._lote_padrao == 0

    def suspender(self) -> None:
        self._situacao = SituacaoAtivo.SUSPENSO.value

    def reativar(self) -> None:
        self._situacao = SituacaoAtivo.NEGOCIAVEL.value

    def atualizar(self, nome: str, lote_padrao: int) -> None:
        self.nome = nome
        self._lote_padrao = lote_padrao


class Cotacao:
    """Última cotação conhecida de um ativo (uma linha por ativo)."""

    def __init__(self, ativo_id: int, preco: Decimal, volume: int, variacao: Decimal, instante: datetime):
        self.ativo_id = ativo_id
        self._preco = q2(preco)
        self._volume = volume
        self._variacao = q2(variacao)
        self._atualizada_em = instante

    @property
    def preco(self) -> Decimal:
        return q2(self._preco)

    @property
    def volume(self) -> int:
        return self._volume

    @property
    def variacao(self) -> Decimal:
        return q2(self._variacao)

    @property
    def atualizada_em(self) -> datetime:
        return self._atualizada_em

    def idade_segundos(self, agora: datetime) -> float:
        return (agora - self._atualizada_em).total_seconds()

    def aceita_atualizacao(self, instante: datetime) -> bool:
        """CSU15: cotações fora de ordem (mais antigas que a atual) são descartadas."""
        return instante >= self._atualizada_em

    def atualizar(self, preco: Decimal, volume: int, variacao: Decimal, instante: datetime) -> None:
        self._preco, self._volume = q2(preco), volume
        self._variacao, self._atualizada_em = q2(variacao), instante
