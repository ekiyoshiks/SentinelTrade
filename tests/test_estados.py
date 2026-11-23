"""Máquina de estados da ordem (CSU04–CSU08): transições permitidas e proibidas."""
import itertools

import pytest

from sentineltrade.dominio.estados import ESTADOS_ALTERAVEIS, ESTADOS_FINAIS, EstadoOrdem as E, MaquinaEstadosOrdem, TRANSICOES
from sentineltrade.dominio.excecoes import TransicaoInvalidaError

PERMITIDAS = {
    (E.CRIADA, E.VALIDADA), (E.CRIADA, E.REJEITADA), (E.VALIDADA, E.ENVIADA), (E.VALIDADA, E.CANCELADA),
    (E.ENVIADA, E.PARCIALMENTE_EXECUTADA), (E.ENVIADA, E.EXECUTADA), (E.ENVIADA, E.REJEITADA),
    (E.ENVIADA, E.CANCELADA), (E.ENVIADA, E.FALHA), (E.PARCIALMENTE_EXECUTADA, E.EXECUTADA),
    (E.PARCIALMENTE_EXECUTADA, E.CANCELADA), (E.FALHA, E.ENVIADA), (E.FALHA, E.INTERVENCAO_MANUAL),
}


def test_tabela_de_transicoes_corresponde_ao_diagrama_da_fase_1():
    reais = {(o, d) for o, ds in TRANSICOES.items() for d in ds}
    assert reais == PERMITIDAS


@pytest.mark.parametrize("origem,destino", sorted(PERMITIDAS, key=str))
def test_transicao_permitida(origem, destino):
    MaquinaEstadosOrdem.validar(origem, destino)


@pytest.mark.parametrize("origem,destino", [p for p in itertools.product(E, E) if p not in PERMITIDAS])
def test_transicao_proibida_levanta_excecao(origem, destino):
    with pytest.raises(TransicaoInvalidaError):
        MaquinaEstadosOrdem.validar(origem, destino)


def test_estados_finais_nao_tem_saida():
    for e in ESTADOS_FINAIS:
        assert not TRANSICOES.get(e)


def test_estados_alteraveis_rn09():
    assert ESTADOS_ALTERAVEIS == {E.VALIDADA, E.ENVIADA, E.PARCIALMENTE_EXECUTADA}
