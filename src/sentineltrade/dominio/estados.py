"""Ciclo de vida da ordem (docs/diagramas/ciclo-de-vida-ordem.md) como máquina de estados."""
from __future__ import annotations

from enum import Enum

from .excecoes import TransicaoInvalidaError


class EstadoOrdem(str, Enum):
    CRIADA = "CRIADA"
    VALIDADA = "VALIDADA"
    ENVIADA = "ENVIADA"
    PARCIALMENTE_EXECUTADA = "PARCIALMENTE_EXECUTADA"
    EXECUTADA = "EXECUTADA"
    REJEITADA = "REJEITADA"
    CANCELADA = "CANCELADA"
    FALHA = "FALHA"
    INTERVENCAO_MANUAL = "INTERVENCAO_MANUAL"


E = EstadoOrdem

# Transições permitidas — espelham o diagrama de estados da fase 1.
TRANSICOES: dict[EstadoOrdem, frozenset[EstadoOrdem]] = {
    E.CRIADA: frozenset({E.VALIDADA, E.REJEITADA}),
    E.VALIDADA: frozenset({E.ENVIADA, E.CANCELADA}),
    E.ENVIADA: frozenset({E.PARCIALMENTE_EXECUTADA, E.EXECUTADA, E.REJEITADA, E.CANCELADA, E.FALHA}),
    E.PARCIALMENTE_EXECUTADA: frozenset({E.EXECUTADA, E.CANCELADA}),
    E.FALHA: frozenset({E.ENVIADA, E.INTERVENCAO_MANUAL}),
    E.EXECUTADA: frozenset(),
    E.REJEITADA: frozenset(),
    E.CANCELADA: frozenset(),
    E.INTERVENCAO_MANUAL: frozenset(),
}

# RN09: somente nestes estados a ordem pode ser alterada ou cancelada.
ESTADOS_ALTERAVEIS = frozenset({E.VALIDADA, E.ENVIADA, E.PARCIALMENTE_EXECUTADA})
ESTADOS_FINAIS = frozenset({E.EXECUTADA, E.REJEITADA, E.CANCELADA, E.INTERVENCAO_MANUAL})
# Estados em que a ordem ainda pode ter reserva de saldo/posição.
ESTADOS_ATIVOS = frozenset({E.VALIDADA, E.ENVIADA, E.PARCIALMENTE_EXECUTADA, E.FALHA})


class MaquinaEstadosOrdem:
    """Valida transições; é a única autoridade sobre o que pode acontecer com uma ordem."""

    @staticmethod
    def pode_transitar(origem: EstadoOrdem, destino: EstadoOrdem) -> bool:
        return destino in TRANSICOES[origem]

    @staticmethod
    def validar(origem: EstadoOrdem, destino: EstadoOrdem) -> None:
        if not MaquinaEstadosOrdem.pode_transitar(origem, destino):
            raise TransicaoInvalidaError(
                f"Transição não permitida: {origem.value} → {destino.value}.",
                detalhes={"origem": origem.value, "destino": destino.value},
            )
