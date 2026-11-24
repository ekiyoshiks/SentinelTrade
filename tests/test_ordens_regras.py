"""Regras de negócio das ordens (RN01–RN09) e ciclo de vida: criar, consultar, alterar, cancelar."""
from decimal import Decimal

import pytest

from sentineltrade.dominio.excecoes import (IndisponibilidadeSeguraError, NaoEncontradoError, RegraNegocioError,
                                            TransicaoInvalidaError, ValidacaoEntradaError, AcessoNegadoError)
from tests.conftest import nova


def test_compra_a_mercado_executa_e_debita_saldo(sis, vinicius):
    antes = sis.ordens.carteira(vinicius)
    o = sis.ordens.enviar(vinicius, nova(qtd=200))
    assert o["estado"] == "VALIDADA"
    sis.tick()
    o = sis.ordens.obter(vinicius, o["id"])
    assert o["estado"] == "EXECUTADA" and o["quantidade_executada"] == 200
    depois = sis.ordens.carteira(vinicius)
    assert Decimal(depois["saldo"]) < Decimal(antes["saldo"])
    assert Decimal(depois["reservado"]) == 0
    assert any(p["ativo"] == "PETR4" and p["quantidade"] >= 200 for p in depois["posicoes"])


def test_rn01_saldo_insuficiente_rejeita_e_persiste(sis, vinicius):
    o = sis.ordens.enviar(vinicius, nova(qtd=1_000_000))
    assert o["estado"] == "REJEITADA" and "aldo" in o["motivo_rejeicao"]
    assert Decimal(sis.ordens.carteira(vinicius)["reservado"]) == 0


def test_rn02_venda_sem_posicao_rejeitada(sis, vinicius):
    o = sis.ordens.enviar(vinicius, nova(ativo="MGLU3", lado="VENDA", qtd=100_000))
    assert o["estado"] == "REJEITADA"


def test_rn02_venda_reserva_posicao_e_libera_no_cancelamento(sis, vinicius):
    sis.ordens.enviar(vinicius, nova(qtd=200)); sis.tick()
    o = sis.ordens.enviar(vinicius, nova(lado="VENDA", modalidade="LIMITADA", qtd=100, preco=sis.provedor.ultimo_preco("PETR4") * Decimal("1.05")))
    pos = next(p for p in sis.ordens.carteira(vinicius)["posicoes"] if p["ativo"] == "PETR4")
    assert pos["reservada"] == 100
    sis.ordens.cancelar(vinicius, o["id"])
    pos = next(p for p in sis.ordens.carteira(vinicius)["posicoes"] if p["ativo"] == "PETR4")
    assert pos["reservada"] == 0


def test_rn03_limite_por_ordem(sis, vinicius, operador):
    sis.risco.definir_limites(operador, vinicius.investidor_id, Decimal("1000"), Decimal("200000"))
    o = sis.ordens.enviar(vinicius, nova(qtd=100))        # ~R$ 3.800 > R$ 1.000
    assert o["estado"] == "REJEITADA" and "imite" in o["motivo_rejeicao"]


def test_rn03_limite_diario(sis, vinicius, operador):
    sis.risco.definir_limites(operador, vinicius.investidor_id, Decimal("5000"), Decimal("5000"))
    assert sis.ordens.enviar(vinicius, nova(qtd=100))["estado"] == "VALIDADA"      # ~3.8k
    assert sis.ordens.enviar(vinicius, nova(qtd=100))["estado"] == "REJEITADA"     # estoura os 5k do dia


def test_rn04_mercado_fechado_rejeita(relogio, vinicius, sis):
    sis.validador  # cadeia padrão
    sis.config = sis.config.__class__(**{**sis.config.__dict__, "mercado_sempre_aberto": False})
    sis.calendario.__init__(sis.config)
    from datetime import datetime
    relogio.definir(datetime(2026, 5, 17, 14, 0))    # domingo
    sis.cotacoes.atualizar()
    o = sis.ordens.enviar(vinicius, nova())
    assert o["estado"] == "REJEITADA"


@pytest.mark.parametrize("qtd", [1, 50, 150])
def test_rn05_quantidade_fora_do_lote_nao_cria_ordem(sis, vinicius, qtd):
    antes = len(sis.ordens.listar(vinicius))
    with pytest.raises(RegraNegocioError) as e:
        sis.ordens.enviar(vinicius, nova(qtd=qtd))
    assert e.value.codigo == "RN05"
    assert len(sis.ordens.listar(vinicius)) == antes


def test_rn06_preco_limitada_fora_da_faixa(sis, vinicius):
    ref = sis.provedor.ultimo_preco("PETR4")
    with pytest.raises(RegraNegocioError) as e:
        sis.ordens.enviar(vinicius, nova(modalidade="LIMITADA", preco=ref * 2))
    assert e.value.codigo == "RN06"


def test_rn06_preco_zero_ou_negativo(sis, vinicius):
    for p in (0, -5):
        with pytest.raises((ValidacaoEntradaError, RegraNegocioError)):
            sis.ordens.enviar(vinicius, nova(modalidade="LIMITADA", preco=p) if p > 0 else
                              __import__("sentineltrade.servicos.ordens", fromlist=["x"]).DadosNovaOrdem("PETR4", "COMPRA", "LIMITADA", 100, Decimal(p)))


def test_rn07_cotacao_defasada_bloqueia_ordem_a_mercado(sis, vinicius, relogio):
    relogio.avancar(seconds=60)          # cotações envelhecem sem nova atualização
    with pytest.raises(RegraNegocioError) as e:
        sis.ordens.enviar(vinicius, nova())
    assert e.value.codigo == "RN07"


@pytest.mark.parametrize("campo,valor", [("lado", "TROCAR"), ("modalidade", "XYZ"), ("ativo", "NAOEXISTE")])
def test_entradas_invalidas(sis, vinicius, campo, valor):
    d = nova(); setattr(d, campo, valor)
    with pytest.raises((ValidacaoEntradaError, NaoEncontradoError)):
        sis.ordens.enviar(vinicius, d)


def test_limitada_sem_preco_e_invalida(sis, vinicius):
    with pytest.raises((ValidacaoEntradaError, RegraNegocioError)):
        sis.ordens.enviar(vinicius, nova(modalidade="LIMITADA"))


# ---------------------------------------------------------------- alterar / cancelar (RN09)
def _limitada_aberta(sis, vinicius, qtd=100):
    preco = (sis.provedor.ultimo_preco("VALE3") * Decimal("0.95")).quantize(Decimal("0.01"))
    o = sis.ordens.enviar(vinicius, nova(ativo="VALE3", modalidade="LIMITADA", qtd=qtd, preco=preco))
    sis.tick()
    return o["id"]


def test_alterar_ordem_aberta_recalcula_reserva(sis, vinicius):
    oid = _limitada_aberta(sis, vinicius)
    r1 = Decimal(sis.ordens.carteira(vinicius)["reservado"])
    o = sis.ordens.alterar(vinicius, oid, quantidade=200)
    assert o["quantidade"] == 200
    assert Decimal(sis.ordens.carteira(vinicius)["reservado"]) > r1


def test_cancelar_libera_reserva_e_vai_para_cancelada(sis, vinicius):
    oid = _limitada_aberta(sis, vinicius)
    assert Decimal(sis.ordens.carteira(vinicius)["reservado"]) > 0
    o = sis.ordens.cancelar(vinicius, oid)
    sis.tick()
    assert sis.ordens.obter(vinicius, oid)["estado"] == "CANCELADA"
    assert Decimal(sis.ordens.carteira(vinicius)["reservado"]) == 0


def test_rn09_nao_altera_nem_cancela_ordem_encerrada(sis, vinicius):
    o = sis.ordens.enviar(vinicius, nova()); sis.tick()
    assert sis.ordens.obter(vinicius, o["id"])["estado"] == "EXECUTADA"
    with pytest.raises((RegraNegocioError, TransicaoInvalidaError)):
        sis.ordens.alterar(vinicius, o["id"], quantidade=300)
    with pytest.raises((RegraNegocioError, TransicaoInvalidaError)):
        sis.ordens.cancelar(vinicius, o["id"])


def test_nao_ve_nem_altera_ordem_de_outro_investidor(sis, vinicius, pedro):
    oid = _limitada_aberta(sis, vinicius)
    with pytest.raises((NaoEncontradoError, AcessoNegadoError)):
        sis.ordens.obter(pedro, oid)
    with pytest.raises((NaoEncontradoError, AcessoNegadoError)):
        sis.ordens.cancelar(pedro, oid)
    assert all(x["id"] != oid for x in sis.ordens.listar(pedro))


def test_historico_registra_cada_transicao(sis, vinicius):
    o = sis.ordens.enviar(vinicius, nova()); sis.tick()
    h = [x["para"] for x in sis.ordens.obter(vinicius, o["id"])["historico"]]
    assert h[0] == "CRIADA" and "VALIDADA" in h and "ENVIADA" in h and h[-1] == "EXECUTADA"


# ---------------------------------------------------------------- RN08 idempotência
def test_rn08_mesma_chave_nao_duplica(sis, vinicius):
    a = sis.ordens.enviar(vinicius, nova(chave="K-1"))
    b = sis.ordens.enviar(vinicius, nova(chave="K-1"))
    assert a["id"] == b["id"] and b.get("duplicada") is True
    assert len(sis.ordens.listar(vinicius)) == 1
    assert Decimal(sis.ordens.carteira(vinicius)["reservado"]) <= Decimal(a["valor_estimado"]) * Decimal("1.06")  # reservou uma vez só
