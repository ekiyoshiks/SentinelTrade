"""Ordem de compra/venda.

``Ordem`` é abstrata; ``OrdemMercado`` e ``OrdemLimitada`` herdam e especializam como o preço
é estimado e quais regras de preço se aplicam (polimorfismo). Todo o estado financeiro
(reservas, execuções) é privado e só muda por métodos que mantêm saldo e posição consistentes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import ClassVar

from .carteira import Conta, Posicao
from .dinheiro import ZERO, q2, q4
from .estados import ESTADOS_ALTERAVEIS, ESTADOS_FINAIS, EstadoOrdem, MaquinaEstadosOrdem
from .excecoes import RegraNegocioError, ValidacaoEntradaError


class Lado(str, Enum):
    COMPRA = "COMPRA"
    VENDA = "VENDA"


class Modalidade(str, Enum):
    MERCADO = "MERCADO"
    LIMITADA = "LIMITADA"


class Ordem(ABC):
    MODALIDADE: ClassVar[Modalidade]

    def __init__(self, *, id: str, chave_idempotencia: str, investidor_id: int, conta_id: int,
                 ativo_id: int, lado: Lado, quantidade: int, preco_limite: Decimal | None,
                 agora: datetime, correlacao_id: str):
        if quantidade <= 0:
            raise ValidacaoEntradaError("A quantidade deve ser positiva.")
        self.id = id
        self.chave_idempotencia = chave_idempotencia
        self.investidor_id = investidor_id
        self.conta_id = conta_id
        self.ativo_id = ativo_id
        self.correlacao_id = correlacao_id
        self._lado = lado.value
        self._quantidade = quantidade
        self._quantidade_executada = 0
        self._preco_limite = q2(preco_limite) if preco_limite is not None else None
        self._preco_reserva = ZERO
        self._valor_estimado = ZERO
        self._valor_reservado = ZERO
        self._quantidade_reservada = 0
        self._preco_medio_execucao = q4(0)
        self._estado = EstadoOrdem.CRIADA.value
        self._tentativas = 0
        self._proxima_tentativa_em: datetime | None = None
        self._cancelamento_pendente = False
        self._motivo_rejeicao: str | None = None
        self.id_bolsa: str | None = None
        self.criado_em = agora
        self.atualizado_em = agora
        self._versao = 1

    # --- fábrica -----------------------------------------------------------
    @staticmethod
    def nova(modalidade: Modalidade, **dados) -> "Ordem":
        classe = {Modalidade.MERCADO: OrdemMercado, Modalidade.LIMITADA: OrdemLimitada}[modalidade]
        if modalidade is Modalidade.LIMITADA and dados.get("preco_limite") is None:
            raise ValidacaoEntradaError("Ordem limitada exige preço.")
        if modalidade is Modalidade.MERCADO:
            dados["preco_limite"] = None
        return classe(**dados)

    # --- polimorfismo ------------------------------------------------------
    @abstractmethod
    def preco_unitario_estimado(self, ultimo_preco: Decimal | None, margem: Decimal) -> Decimal:
        """Preço usado para estimar valor e reservar saldo."""

    @abstractmethod
    def exige_cotacao_fresca(self) -> bool:
        """RN07 aplica-se apenas a ordens a mercado."""

    @abstractmethod
    def exige_preco_na_faixa(self) -> bool:
        """RN06 aplica-se apenas a ordens limitadas."""

    @property
    def modalidade(self) -> Modalidade:
        return self.MODALIDADE

    # --- leitura -----------------------------------------------------------
    @property
    def lado(self) -> Lado:
        return Lado(self._lado)

    @property
    def estado(self) -> EstadoOrdem:
        return EstadoOrdem(self._estado)

    @property
    def quantidade(self) -> int:
        return self._quantidade

    @property
    def quantidade_executada(self) -> int:
        return self._quantidade_executada

    @property
    def quantidade_restante(self) -> int:
        return self._quantidade - self._quantidade_executada

    @property
    def preco_limite(self) -> Decimal | None:
        return q2(self._preco_limite) if self._preco_limite is not None else None

    @property
    def preco_medio_execucao(self) -> Decimal:
        return q4(self._preco_medio_execucao)

    @property
    def valor_estimado(self) -> Decimal:
        return q2(self._valor_estimado)

    @property
    def valor_reservado(self) -> Decimal:
        return q2(self._valor_reservado)

    @property
    def quantidade_reservada(self) -> int:
        return self._quantidade_reservada

    @property
    def tentativas(self) -> int:
        return self._tentativas

    @property
    def proxima_tentativa_em(self) -> datetime | None:
        return self._proxima_tentativa_em

    @property
    def cancelamento_pendente(self) -> bool:
        return bool(self._cancelamento_pendente)

    @property
    def motivo_rejeicao(self) -> str | None:
        return self._motivo_rejeicao

    @property
    def versao(self) -> int:
        return self._versao

    @property
    def alteravel(self) -> bool:
        """RN09."""
        return self.estado in ESTADOS_ALTERAVEIS

    @property
    def finalizada(self) -> bool:
        return self.estado in ESTADOS_FINAIS

    @property
    def valor_a_reservar(self) -> Decimal:
        """Valor que a ordem precisa ter reservado agora (compra: restante × preço de reserva)."""
        if self.lado is Lado.COMPRA:
            return q2(self._preco_reserva * self.quantidade_restante)
        return ZERO

    # --- avaliação e reserva ----------------------------------------------
    def definir_valuacao(self, preco_unitario: Decimal) -> None:
        self._preco_reserva = q2(preco_unitario)
        self._valor_estimado = q2(self._preco_reserva * self._quantidade)

    def reservar(self, conta: Conta, posicao: Posicao | None) -> None:
        """Reserva saldo (compra, RN01) ou posição (venda, RN02)."""
        if self.lado is Lado.COMPRA:
            valor = self.valor_a_reservar
            conta.reservar(valor)
            self._valor_reservado = valor
        else:
            if posicao is None:
                raise RegraNegocioError("Posição insuficiente: disponível 0.", codigo="RN02",
                                        rejeita_ordem=True)
            posicao.reservar(self.quantidade_restante)
            self._quantidade_reservada = self.quantidade_restante

    def liberar_reservas(self, conta: Conta, posicao: Posicao | None) -> None:
        """Devolve tudo que ainda estiver reservado (cancelamento, rejeição, fim de ordem)."""
        if self._valor_reservado > 0:
            conta.liberar(self._valor_reservado)
            self._valor_reservado = ZERO
        if self._quantidade_reservada > 0 and posicao is not None:
            posicao.liberar(self._quantidade_reservada)
        self._quantidade_reservada = 0

    # --- transições --------------------------------------------------------
    def transitar(self, novo: EstadoOrdem, agora: datetime, motivo: str | None = None) -> None:
        MaquinaEstadosOrdem.validar(self.estado, novo)
        self._estado = novo.value
        self.atualizado_em = agora
        self._versao += 1
        if novo is EstadoOrdem.REJEITADA:
            self._motivo_rejeicao = motivo

    def marcar_enviada(self, agora: datetime, id_bolsa: str | None = None) -> None:
        if self.estado is not EstadoOrdem.ENVIADA:
            self.transitar(EstadoOrdem.ENVIADA, agora)
        if id_bolsa:
            self.id_bolsa = id_bolsa
        self._proxima_tentativa_em = None

    def marcar_falha(self, agora: datetime, proxima_tentativa: datetime | None) -> None:
        self.transitar(EstadoOrdem.FALHA, agora)
        self._proxima_tentativa_em = proxima_tentativa

    def registrar_tentativa(self, agora: datetime, proxima: datetime | None) -> None:
        self._tentativas += 1
        self._proxima_tentativa_em = proxima
        self.atualizado_em = agora

    def encerrar_tentativas(self, agora: datetime) -> None:
        """Sem nova tentativa agendada (limite atingido ou pendência resolvida)."""
        self._proxima_tentativa_em = None
        self.atualizado_em = agora

    def marcar_cancelamento_pendente(self, pendente: bool, agora: datetime) -> None:
        self._cancelamento_pendente = pendente
        self.atualizado_em = agora

    # --- execução ----------------------------------------------------------
    def aplicar_execucao(self, quantidade: int, preco: Decimal, conta: Conta,
                         posicao: Posicao, agora: datetime) -> Decimal:
        """Registra uma execução (total ou parcial) e atualiza saldo e posição de forma atômica.

        Retorna o valor financeiro da execução.
        """
        if self.estado not in (EstadoOrdem.ENVIADA, EstadoOrdem.PARCIALMENTE_EXECUTADA):
            raise RegraNegocioError(
                f"Ordem em {self.estado.value} não pode receber execução.", codigo="RN09")
        if quantidade <= 0 or quantidade > self.quantidade_restante:
            raise RegraNegocioError("Quantidade executada inválida.", codigo="EXECUCAO_INVALIDA")
        preco = q2(preco)
        custo = q2(preco * quantidade)

        if self.lado is Lado.COMPRA:
            liberada = min(self._valor_reservado, q2(self._preco_reserva * quantidade))
            conta.executar_compra(custo, liberada)
            self._valor_reservado = q2(self._valor_reservado - liberada)
            posicao.registrar_compra(quantidade, preco)
        else:
            posicao.registrar_venda(quantidade)
            conta.creditar(custo)
            self._quantidade_reservada = max(0, self._quantidade_reservada - quantidade)

        total_anterior = self._preco_medio_execucao * self._quantidade_executada
        self._quantidade_executada += quantidade
        self._preco_medio_execucao = q4((total_anterior + preco * quantidade) / self._quantidade_executada)

        novo = (EstadoOrdem.EXECUTADA if self.quantidade_restante == 0
                else EstadoOrdem.PARCIALMENTE_EXECUTADA)
        if novo is not self.estado:
            self.transitar(novo, agora)
        else:
            self.atualizado_em = agora
            self._versao += 1
        if novo is EstadoOrdem.EXECUTADA:
            self.liberar_reservas(conta, posicao)  # devolve eventual sobra de reserva
        return custo

    # --- alteração (CSU05) -------------------------------------------------
    def modificar(self, nova_quantidade: int, novo_preco_limite: Decimal | None,
                  preco_unitario: Decimal, agora: datetime) -> None:
        """Aplica nova quantidade/preço. As reservas devem ter sido liberadas antes."""
        if not self.alteravel:
            raise RegraNegocioError(f"Ordem em {self.estado.value} não pode ser alterada.", codigo="RN09")
        if nova_quantidade < self._quantidade_executada or nova_quantidade <= 0:
            raise ValidacaoEntradaError("Nova quantidade menor que a já executada.")
        self._quantidade = nova_quantidade
        if novo_preco_limite is not None:
            self._preco_limite = q2(novo_preco_limite)
        self.definir_valuacao(preco_unitario)
        self.atualizado_em = agora
        self._versao += 1


class OrdemMercado(Ordem):
    MODALIDADE = Modalidade.MERCADO

    def preco_unitario_estimado(self, ultimo_preco: Decimal | None, margem: Decimal) -> Decimal:
        if ultimo_preco is None:
            raise RegraNegocioError("Sem cotação disponível para ordem a mercado.", codigo="RN07")
        if self.lado is Lado.COMPRA:
            return q2(ultimo_preco * (Decimal("1") + margem))  # margem de segurança na reserva
        return q2(ultimo_preco)

    def exige_cotacao_fresca(self) -> bool:
        return True

    def exige_preco_na_faixa(self) -> bool:
        return False


class OrdemLimitada(Ordem):
    MODALIDADE = Modalidade.LIMITADA

    def preco_unitario_estimado(self, ultimo_preco: Decimal | None, margem: Decimal) -> Decimal:
        assert self._preco_limite is not None
        return q2(self._preco_limite)

    def exige_cotacao_fresca(self) -> bool:
        return False

    def exige_preco_na_faixa(self) -> bool:
        return True
