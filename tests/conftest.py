"""Fixtures: sistema completo em SQLite de memória, relógio controlável e dados de demonstração."""
from datetime import datetime
from decimal import Decimal

import pytest

from sentineltrade import seed
from sentineltrade.config import Configuracoes
from sentineltrade.dominio.relogio import RelogioFixo
from sentineltrade.servicos.ordens import DadosNovaOrdem
from sentineltrade.servicos.sistema import Sistema


@pytest.fixture
def relogio():
    return RelogioFixo(datetime(2026, 5, 18, 14, 0, 0))   # segunda-feira, pregão aberto


@pytest.fixture
def sis(relogio):
    s = Sistema(Configuracoes(database_url="sqlite://", mercado_sempre_aberto=True), relogio=relogio)
    s.banco.criar_tabelas()
    seed.popular(s)
    s.cotacoes.atualizar()
    return s


def entrar(sis, login):
    d = sis.autenticacao.iniciar_login(login, seed.senha_demo())
    usuario, _ = sis.autenticacao.validar_mfa(d.desafio_id, sis.notificador.ultimo_codigo(login))
    return usuario


@pytest.fixture
def vinicius(sis):
    return entrar(sis, "vinicius")


@pytest.fixture
def pedro(sis):
    return entrar(sis, "pedro")


@pytest.fixture
def operador(sis):
    return entrar(sis, "operador")


@pytest.fixture
def admin(sis):
    return entrar(sis, "admin")


@pytest.fixture
def auditor(sis):
    return entrar(sis, "auditor")


def nova(ativo="PETR4", lado="COMPRA", modalidade="MERCADO", qtd=100, preco=None, chave=None):
    return DadosNovaOrdem(ativo, lado, modalidade, qtd, Decimal(str(preco)) if preco else None,
                          chave_idempotencia=chave)
