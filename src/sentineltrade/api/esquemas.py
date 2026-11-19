"""Esquemas de entrada (RNF-05: toda entrada é validada por tipo, tamanho, formato e faixa)."""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    login: str = Field(min_length=1, max_length=60)
    senha: str = Field(min_length=1, max_length=200)


class MfaIn(BaseModel):
    desafio_id: str = Field(min_length=10, max_length=60)
    codigo: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class ReenviarIn(BaseModel):
    desafio_id: str = Field(min_length=10, max_length=60)


class OrdemIn(BaseModel):
    ativo: str = Field(min_length=1, max_length=12)
    lado: str = Field(pattern=r"^(COMPRA|VENDA)$")
    modalidade: str = Field(pattern=r"^(MERCADO|LIMITADA)$")
    quantidade: int = Field(gt=0, le=10_000_000)
    preco: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)


class OrdemAlterarIn(BaseModel):
    quantidade: int | None = Field(default=None, gt=0, le=10_000_000)
    preco: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)


class LimitesIn(BaseModel):
    max_por_ordem: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    max_diario: Decimal = Field(gt=0, max_digits=14, decimal_places=2)


class SuspensaoIn(BaseModel):
    escopo: str = Field(default="MERCADO", max_length=12)
    motivo: str = Field(min_length=3, max_length=300)


class EscopoIn(BaseModel):
    escopo: str = Field(default="MERCADO", max_length=12)


class InvestidorIn(BaseModel):
    nome: str = Field(min_length=2, max_length=120)
    documento: str = Field(min_length=3, max_length=20)
    login: str = Field(min_length=3, max_length=60, pattern=r"^[A-Za-z0-9_.-]+$")
    senha: str = Field(min_length=1, max_length=200)
    saldo_inicial: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    max_por_ordem: Decimal = Field(default=Decimal("50000"), gt=0, max_digits=14, decimal_places=2)
    max_diario: Decimal = Field(default=Decimal("200000"), gt=0, max_digits=14, decimal_places=2)


class InvestidorNomeIn(BaseModel):
    nome: str = Field(min_length=2, max_length=120)


class SituacaoIn(BaseModel):
    ativo: bool


class DepositoIn(BaseModel):
    valor: Decimal = Field(gt=0, max_digits=14, decimal_places=2)


class AtivoIn(BaseModel):
    codigo: str = Field(min_length=3, max_length=12, pattern=r"^[A-Za-z0-9]+$")
    nome: str = Field(min_length=2, max_length=120)
    tipo: str = Field(pattern=r"^(ACAO|ETF|FII)$")
    lote_padrao: int = Field(gt=0, le=100_000)
    preco_inicial: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class AtivoAtualizarIn(BaseModel):
    nome: str | None = Field(default=None, min_length=2, max_length=120)
    lote_padrao: int | None = Field(default=None, gt=0, le=100_000)
    situacao: str | None = Field(default=None, pattern=r"^(NEGOCIAVEL|SUSPENSO)$")


class UsuarioInternoIn(BaseModel):
    login: str = Field(min_length=3, max_length=60, pattern=r"^[A-Za-z0-9_.-]+$")
    senha: str = Field(min_length=1, max_length=200)
    perfil: str = Field(max_length=20)


class PerfilIn(BaseModel):
    perfil: str = Field(max_length=20)


class SituacaoUsuarioIn(BaseModel):
    ativo: bool | None = None
    desbloquear: bool = False


class SimulacaoBolsaIn(BaseModel):
    modo: str | None = Field(default=None, pattern=r"^(NORMAL|SEM_RESPOSTA|RESPOSTA_PERDIDA)$")
    execucao_parcial: bool | None = None
    rejeitar_proximas: int | None = Field(default=None, ge=0, le=100)
    duplicar_retorno: bool | None = None


class SimulacaoProvedorIn(BaseModel):
    pausado: bool | None = None
    atraso_s: int | None = Field(default=None, ge=0, le=3600)


class SimulacaoNotificadorIn(BaseModel):
    falhar: bool
