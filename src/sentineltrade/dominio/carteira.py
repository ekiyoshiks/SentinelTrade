"""Conta (saldo) e Posição (ativos em carteira).

Saldo, reserva e quantidades são privados: só mudam por métodos que mantêm as
invariantes (saldo ≥ 0, reservado ≤ saldo — RNF-17) e nunca permitem venda a descoberto (RN02).
"""
from __future__ import annotations

from decimal import Decimal

from .dinheiro import ZERO, q2, q4
from .excecoes import RegraNegocioError


class Conta:
    def __init__(self, investidor_id: int, saldo: Decimal = ZERO):
        self.investidor_id = investidor_id
        self._saldo = q2(saldo)
        self._reservado = ZERO

    @property
    def saldo(self) -> Decimal:
        return q2(self._saldo)

    @property
    def reservado(self) -> Decimal:
        return q2(self._reservado)

    @property
    def disponivel(self) -> Decimal:
        return q2(self._saldo - self._reservado)

    def depositar(self, valor: Decimal) -> None:
        valor = q2(valor)
        if valor <= 0:
            raise RegraNegocioError("O valor do depósito deve ser positivo.", codigo="VALOR_INVALIDO")
        self._saldo = q2(self._saldo + valor)

    def reservar(self, valor: Decimal) -> None:
        valor = q2(valor)
        if valor > self.disponivel:
            raise RegraNegocioError(
                f"Saldo insuficiente: disponível R$ {self.disponivel}.",
                codigo="RN01", rejeita_ordem=True,
            )
        self._reservado = q2(self._reservado + valor)

    def liberar(self, valor: Decimal) -> None:
        valor = q2(valor)
        self._reservado = q2(max(ZERO, self._reservado - valor))

    def executar_compra(self, custo: Decimal, reserva_liberada: Decimal) -> None:
        """Debita o custo real e libera a parte da reserva correspondente (tudo ou nada)."""
        custo, reserva_liberada = q2(custo), q2(reserva_liberada)
        novo_saldo = q2(self._saldo - custo)
        nova_reserva = q2(max(ZERO, self._reservado - reserva_liberada))
        if novo_saldo < 0 or novo_saldo < nova_reserva:
            raise RegraNegocioError("A execução deixaria o saldo inconsistente.", codigo="RNF-17")
        self._saldo, self._reservado = novo_saldo, nova_reserva

    def creditar(self, valor: Decimal) -> None:
        self._saldo = q2(self._saldo + q2(valor))


class Posicao:
    def __init__(self, conta_id: int, ativo_id: int):
        self.conta_id = conta_id
        self.ativo_id = ativo_id
        self._quantidade = 0
        self._reservada = 0
        self._preco_medio = q4(0)

    @property
    def quantidade(self) -> int:
        return self._quantidade

    @property
    def reservada(self) -> int:
        return self._reservada

    @property
    def disponivel(self) -> int:
        return self._quantidade - self._reservada

    @property
    def preco_medio(self) -> Decimal:
        return q4(self._preco_medio)

    def reservar(self, quantidade: int) -> None:
        if quantidade > self.disponivel:
            raise RegraNegocioError(
                f"Posição insuficiente: disponível {self.disponivel}.", codigo="RN02", rejeita_ordem=True
            )
        self._reservada += quantidade

    def liberar(self, quantidade: int) -> None:
        self._reservada = max(0, self._reservada - quantidade)

    def registrar_compra(self, quantidade: int, preco: Decimal) -> None:
        total = self._preco_medio * self._quantidade + Decimal(str(preco)) * quantidade
        self._quantidade += quantidade
        self._preco_medio = q4(total / self._quantidade)

    def registrar_venda(self, quantidade: int) -> None:
        if quantidade > self._quantidade:
            raise RegraNegocioError("Venda a descoberto não é permitida.", codigo="RN02")
        self._quantidade -= quantidade
        self._reservada = max(0, self._reservada - quantidade)
        if self._quantidade == 0:
            self._preco_medio = q4(0)

    def resultado(self, preco_atual: Decimal) -> Decimal:
        """Resultado financeiro não realizado da posição."""
        return q2((Decimal(str(preco_atual)) - self._preco_medio) * self._quantidade)
