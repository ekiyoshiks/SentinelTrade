"""Falhas da Bolsa e filas: timeout, reprocesso (CSU18), execução parcial, retorno duplicado, indisponibilidade segura."""
from decimal import Decimal

import pytest

from sentineltrade.dominio.excecoes import IndisponibilidadeSeguraError
from tests.conftest import nova


def estado(sis, u, oid):
    return sis.ordens.obter(u, oid)["estado"]


def test_bolsa_sem_resposta_marca_falha_e_reprocessa_ao_voltar(sis, vinicius):
    sis.bolsa.modo = "SEM_RESPOSTA"
    o = sis.ordens.enviar(vinicius, nova())
    sis.tick()
    assert estado(sis, vinicius, o["id"]) in {"FALHA", "VALIDADA"}      # nunca "perdida" nem duplicada
    assert Decimal(sis.ordens.carteira(vinicius)["reservado"]) > 0       # reserva mantida enquanto indefinida
    sis.bolsa.modo = "NORMAL"
    for _ in range(6):
        sis.relogio.avancar(seconds=120); sis.cotacoes.atualizar(); sis.tick()
    assert estado(sis, vinicius, o["id"]) == "EXECUTADA"
    assert len([x for x in sis.ordens.listar(vinicius)]) == 1


def test_resposta_perdida_nao_gera_ordem_duplicada_na_bolsa(sis, vinicius):
    sis.bolsa.modo = "RESPOSTA_PERDIDA"      # a Bolsa recebe, mas a resposta se perde
    o = sis.ordens.enviar(vinicius, nova())
    sis.tick()
    sis.bolsa.modo = "NORMAL"
    for _ in range(6):
        sis.relogio.avancar(seconds=120); sis.cotacoes.atualizar(); sis.tick()
    final = sis.ordens.obter(vinicius, o["id"])
    assert final["estado"] == "EXECUTADA" and final["quantidade_executada"] == 100   # executada UMA vez
    assert sis.bolsa.consultar(final["chave_idempotencia"]) is not None


def test_esgotadas_as_tentativas_vai_para_intervencao_manual_e_notifica(sis, vinicius):
    sis.bolsa.modo = "SEM_RESPOSTA"
    o = sis.ordens.enviar(vinicius, nova())
    for _ in range(12):
        sis.relogio.avancar(seconds=300); sis.cotacoes.atualizar(); sis.tick()
    assert estado(sis, vinicius, o["id"]) == "INTERVENCAO_MANUAL"
    assert any("INTERV" in n["tipo"].upper() or "manual" in n["mensagem"].lower() for n in sis.consultas.notificacoes(vinicius))


def test_execucao_parcial_depois_total(sis, vinicius):
    sis.bolsa.execucao_parcial = True
    o = sis.ordens.enviar(vinicius, nova(qtd=200))
    sis.tick()
    vistos = {estado(sis, vinicius, o["id"])}
    for _ in range(3):
        sis.tick(); vistos.add(estado(sis, vinicius, o["id"]))
    assert "EXECUTADA" in vistos
    assert sis.ordens.obter(vinicius, o["id"])["quantidade_executada"] == 200


def test_bolsa_rejeita_ordem_libera_reserva(sis, vinicius):
    sis.bolsa.rejeitar_proximas = 1
    o = sis.ordens.enviar(vinicius, nova())
    sis.tick(); sis.tick()
    assert estado(sis, vinicius, o["id"]) == "REJEITADA"
    assert Decimal(sis.ordens.carteira(vinicius)["reservado"]) == 0


def test_retorno_duplicado_da_bolsa_e_processado_uma_unica_vez(sis, vinicius):
    sis.bolsa.duplicar_retorno = True
    saldo0 = Decimal(sis.ordens.carteira(vinicius)["saldo"])
    o = sis.ordens.enviar(vinicius, nova(qtd=100))
    for _ in range(3):
        sis.tick()
    ord_ = sis.ordens.obter(vinicius, o["id"])
    assert ord_["estado"] == "EXECUTADA" and ord_["quantidade_executada"] == 100
    assert len(ord_["operacoes"]) == 1
    gasto = saldo0 - Decimal(sis.ordens.carteira(vinicius)["saldo"])
    assert gasto == Decimal(ord_["preco_medio_execucao"]) * 100


def test_cancelamento_concorrente_com_execucao_e_consistente(sis, vinicius):
    """Antes de cancelar o sistema sincroniza os retornos: ou cancela só o restante, ou recusa (já executada)."""
    from sentineltrade.dominio.excecoes import TransicaoInvalidaError
    sis.bolsa.execucao_parcial = True
    o = sis.ordens.enviar(vinicius, nova(qtd=200))
    sis.tick()
    try:
        sis.ordens.cancelar(vinicius, o["id"])
        final = sis.ordens.obter(vinicius, o["id"])
        assert final["estado"] == "CANCELADA" and final["quantidade_executada"] < 200
    except TransicaoInvalidaError:
        assert sis.ordens.obter(vinicius, o["id"])["estado"] == "EXECUTADA"
    assert Decimal(sis.ordens.carteira(vinicius)["reservado"]) == 0


# ---------------------------------------------------------------- indisponibilidade segura (CSU13)
def test_suspensao_manual_bloqueia_novas_ordens_mas_permite_consultar_e_cancelar(sis, vinicius, operador):
    preco = (sis.provedor.ultimo_preco("VALE3") * Decimal("0.95")).quantize(Decimal("0.01"))
    aberta = sis.ordens.enviar(vinicius, nova(ativo="VALE3", modalidade="LIMITADA", preco=preco))["id"]
    sis.tick()
    sis.risco.acionar_suspensao(operador, "MERCADO", "anomalia nas cotações")
    with pytest.raises(IndisponibilidadeSeguraError):
        sis.ordens.enviar(vinicius, nova())
    assert sis.ordens.obter(vinicius, aberta)["id"] == aberta            # consulta continua
    sis.ordens.cancelar(vinicius, aberta)                                # cancelamento continua
    sis.risco.encerrar_suspensao(operador, "MERCADO")
    assert sis.ordens.enviar(vinicius, nova())["estado"] == "VALIDADA"


def test_suspensao_por_ativo_nao_afeta_outros(sis, vinicius, operador):
    sis.risco.acionar_suspensao(operador, "PETR4", "teste")
    with pytest.raises(IndisponibilidadeSeguraError):
        sis.ordens.enviar(vinicius, nova(ativo="PETR4"))
    assert sis.ordens.enviar(vinicius, nova(ativo="VALE3"))["estado"] == "VALIDADA"


def test_erro_inesperado_aciona_suspensao_automatica(sis, vinicius, monkeypatch):
    def quebrar(*a, **k):
        raise RuntimeError("falha interna simulada")
    monkeypatch.setattr(sis.ordens, "_validar_e_reservar", quebrar, raising=False)
    monkeypatch.setattr(sis.validador, "validar", quebrar)
    with pytest.raises(Exception):
        sis.ordens.enviar(vinicius, nova())
    with pytest.raises(IndisponibilidadeSeguraError):
        sis.ordens.enviar(vinicius, nova())


def test_cotacoes_defasadas_nao_derrubam_o_sistema(sis, vinicius):
    sis.provedor.pausado = True
    sis.relogio.avancar(seconds=60); sis.cotacoes.atualizar()
    st = sis.status_integracoes()
    assert st["provedor_pausado"] is True
    assert sis.ordens.listar(vinicius) == []        # consultas seguem funcionando
