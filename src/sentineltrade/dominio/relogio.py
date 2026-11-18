"""Abstração do relógio: permite testar regras que dependem de horário (RN04, RN07, RN11).

Todos os instantes do sistema são UTC "ingênuos" (sem tzinfo). A conversão para o fuso
do pregão acontece apenas na regra de mercado aberto.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone


class Relogio(ABC):
    @abstractmethod
    def agora(self) -> datetime:
        """Instante atual em UTC, sem tzinfo."""


class RelogioSistema(Relogio):
    def agora(self) -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)


class RelogioFixo(Relogio):
    """Relógio controlável, usado nos testes e na simulação."""

    def __init__(self, instante: datetime):
        self._instante = instante

    def agora(self) -> datetime:
        return self._instante

    def avancar(self, **kwargs) -> None:
        self._instante += timedelta(**kwargs)

    def definir(self, instante: datetime) -> None:
        self._instante = instante
