"""Contratos dos sistemas externos (atores secundários).

O núcleo do sistema só conhece estas interfaces; trocar o simulador por um sistema real
não exige mudar regras nem serviços (separação interface / regra / integração).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


@dataclass(frozen=True)
class CotacaoRecebida:
    codigo: str
    preco: Decimal
    volume: int
    variacao: Decimal
    instante: datetime


class ProvedorCotacoes(ABC):
    @abstractmethod
    def obter(self) -> list[CotacaoRecebida]:
        """Lê as cotações mais recentes. Pode lançar ``IntegracaoTimeoutError``."""


@dataclass(frozen=True)
class PedidoBolsa:
    chave: str                # chave de idempotência da ordem
    codigo_ativo: str
    lado: str                 # COMPRA | VENDA
    modalidade: str           # MERCADO | LIMITADA
    quantidade: int
    preco_limite: Decimal | None
    lote: int = 100


@dataclass(frozen=True)
class RespostaBolsa:
    id_bolsa: str
    ja_conhecida: bool = False


class TipoRetorno(str, Enum):
    EXECUCAO_TOTAL = "EXECUCAO_TOTAL"
    EXECUCAO_PARCIAL = "EXECUCAO_PARCIAL"
    REJEICAO = "REJEICAO"
    CANCELAMENTO = "CANCELAMENTO"


@dataclass(frozen=True)
class RetornoBolsa:
    id_evento: str
    chave: str
    tipo: str
    quantidade: int = 0
    preco: Decimal | None = None
    motivo: str | None = None


@dataclass(frozen=True)
class StatusBolsa:
    id_bolsa: str
    situacao: str
    quantidade_executada: int


class BolsaGateway(ABC):
    @abstractmethod
    def enviar(self, pedido: PedidoBolsa) -> RespostaBolsa:
        """Transmite a ordem. Idempotente pela chave. Pode lançar ``IntegracaoTimeoutError``."""

    @abstractmethod
    def alterar(self, chave: str, quantidade: int, preco_limite: Decimal | None) -> None:
        """Altera uma ordem. Lança ``BolsaRecusouError`` se já executada."""

    @abstractmethod
    def cancelar(self, chave: str) -> int:
        """Cancela e devolve a quantidade já executada. ``BolsaRecusouError`` se já executada."""

    @abstractmethod
    def consultar(self, chave: str) -> StatusBolsa | None:
        """Devolve o status da ordem ou ``None`` se a Bolsa não a conhece (CSU18)."""

    @abstractmethod
    def coletar_retornos(self) -> list[RetornoBolsa]:
        """Retornos ainda não confirmados (execução, rejeição, cancelamento)."""

    @abstractmethod
    def confirmar_retorno(self, id_evento: str) -> None:
        """Confirma o processamento de um retorno, para que não seja reentregue."""

    @abstractmethod
    def saude(self) -> bool: ...


class Notificador(ABC):
    @abstractmethod
    def entregar(self, destinatario: str, mensagem: str) -> None:
        """Entrega uma mensagem. Lança ``IntegracaoError`` em caso de falha."""

    @abstractmethod
    def enviar_codigo_mfa(self, login: str, codigo: str) -> None:
        """Entrega o código de uso único do segundo fator."""
