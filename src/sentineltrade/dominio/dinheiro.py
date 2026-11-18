"""Utilitários monetários: toda aritmética financeira usa Decimal com 2 casas."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0.00")
_DOIS = Decimal("0.01")
_QUATRO = Decimal("0.0001")


def q2(valor: Decimal | int | float | str) -> Decimal:
    return Decimal(str(valor)).quantize(_DOIS, rounding=ROUND_HALF_UP)


def q4(valor: Decimal | int | float | str) -> Decimal:
    return Decimal(str(valor)).quantize(_QUATRO, rounding=ROUND_HALF_UP)


def dec(valor: Decimal | int | float | str | None) -> Decimal | None:
    return None if valor is None else Decimal(str(valor))
