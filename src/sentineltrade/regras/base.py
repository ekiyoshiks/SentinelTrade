"""Contrato das regras de negócio e contexto de validação."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from ..config import Configuracoes
from ..dominio.carteira import Conta, Posicao
from ..dominio.mercado import Ativo, Cotacao
from ..dominio.ordens import Ordem
from ..dominio.risco import LimiteRisco


@dataclass
class ContextoValidacao:
    """Tudo que as regras precisam saber para validar uma ordem (CSU04, passo 5)."""

    ordem: Ordem
    conta: Conta
    posicao: Posicao | None
    ativo: Ativo
    cotacao: Cotacao | None
    limite: LimiteRisco | None
    total_dia: Decimal
    agora: datetime
    mercado_aberto: bool
    proximo_pregao: str
    config: Configuracoes


class RegraNegocio(ABC):
    """Uma regra de negócio. Lança ``RegraNegocioError`` quando violada."""

    codigo: str = "RN00"
    descricao: str = ""

    @abstractmethod
    def validar(self, ctx: ContextoValidacao) -> None: ...
