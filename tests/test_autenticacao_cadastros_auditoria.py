"""CSU01 (login + MFA), RN10/RN11, perfis/alçadas (CSU09–11) e auditoria imutável com cadeia de hash (CSU14)."""
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from sentineltrade import seed
from sentineltrade.dominio.excecoes import (AcessoNegadoError, AutenticacaoError, ContaBloqueadaError,
                                            RegraNegocioError, ConflitoError, SentinelTradeError)
from tests.conftest import entrar, nova


# ------------------------------------------------------------------ login / MFA
def test_login_exige_segundo_fator(sis):
    d = sis.autenticacao.iniciar_login("ana", seed.senha_demo())
    assert d.desafio_id and sis.notificador.ultimo_codigo("ana")
    u, token = sis.autenticacao.validar_mfa(d.desafio_id, sis.notificador.ultimo_codigo("ana"))
    assert u.login == "ana" and sis.autenticacao.usuario_do_token(token).login == "ana"


def test_senha_incorreta_mensagem_generica(sis):
    with pytest.raises(AutenticacaoError) as a:
        sis.autenticacao.iniciar_login("ana", "senha-errada-123")
    with pytest.raises(AutenticacaoError) as b:
        sis.autenticacao.iniciar_login("usuario-inexistente", "senha-errada-123")
    assert str(a.value) == str(b.value)           # não revela se o usuário existe


def test_codigo_mfa_invalido_e_expirado(sis):
    d = sis.autenticacao.iniciar_login("ana", seed.senha_demo())
    with pytest.raises(AutenticacaoError) as e:
        sis.autenticacao.validar_mfa(d.desafio_id, "000000" if sis.notificador.ultimo_codigo("ana") != "000000" else "111111")
    assert e.value.codigo == "MFA_INVALIDO"
    cod = sis.notificador.ultimo_codigo("ana")
    sis.relogio.avancar(seconds=61)
    with pytest.raises(AutenticacaoError) as e:
        sis.autenticacao.validar_mfa(d.desafio_id, cod)
    assert e.value.codigo == "MFA_EXPIRADO"


def test_codigo_mfa_nao_pode_ser_reutilizado(sis):
    d = sis.autenticacao.iniciar_login("ana", seed.senha_demo())
    cod = sis.notificador.ultimo_codigo("ana")
    sis.autenticacao.validar_mfa(d.desafio_id, cod)
    with pytest.raises(AutenticacaoError):
        sis.autenticacao.validar_mfa(d.desafio_id, cod)


def test_rn11_bloqueio_apos_tentativas_e_desbloqueio_por_tempo(sis):
    for _ in range(sis.config.mfa_max_tentativas):
        try:
            sis.autenticacao.iniciar_login("bruno", "errada-errada-1")
        except SentinelTradeError:
            pass
    with pytest.raises(ContaBloqueadaError):
        sis.autenticacao.iniciar_login("bruno", seed.senha_demo())     # mesmo com a senha certa
    sis.relogio.avancar(minutes=sis.config.bloqueio_minutos + 1)
    assert entrar(sis, "bruno").login == "bruno"


def test_token_adulterado_e_rejeitado(sis, ana):
    token = sis.autenticacao.emitir_token(ana)
    with pytest.raises(AutenticacaoError):
        sis.autenticacao.usuario_do_token(token[:-3] + "xxx")


def test_token_expira(sis, ana):
    token = sis.autenticacao.emitir_token(ana)
    sis.relogio.avancar(seconds=sis.config.sessao_validade_segundos + 5)
    with pytest.raises(AutenticacaoError):
        sis.autenticacao.usuario_do_token(token)


@pytest.mark.parametrize("senha", ["curta1A", "somenteletrasaquiabc", "123456789012345", ""])
def test_rn10_politica_de_senha(sis, admin, senha):
    with pytest.raises(RegraNegocioError) as e:
        sis.cadastros.criar_investidor(admin, nome="Novo", documento="123", login="novo", senha=senha)
    assert e.value.codigo == "RN10"


def test_senha_armazenada_como_hash_argon2(sis):
    with sis.banco.transacao() as s:
        h = s.execute(text("select senha_hash from usuarios where login='ana'")).scalar_one()
    assert h.startswith("$argon2") and seed.senha_demo() not in h


# ------------------------------------------------------------------ perfis e alçadas
def test_investidor_nao_acessa_funcoes_administrativas(sis, ana):
    with pytest.raises(AcessoNegadoError):
        sis.cadastros.listar_usuarios(ana)
    with pytest.raises(AcessoNegadoError):
        sis.consultas.painel(ana)
    with pytest.raises(AcessoNegadoError):
        sis.risco.acionar_suspensao(ana, "MERCADO", "tentativa indevida")


def test_operador_e_auditor_nao_operam_ordens(sis, operador, auditor):
    for u in (operador, auditor):
        with pytest.raises(AcessoNegadoError):
            sis.ordens.enviar(u, nova())


def test_admin_nao_concede_perfil_administrador(sis, admin):
    with pytest.raises(SentinelTradeError):
        sis.cadastros.criar_usuario_interno(admin, login="outroadmin", senha="Senha@Forte2026x", perfil="ADMINISTRADOR")


def test_admin_cria_investidor_e_ele_consegue_logar(sis, admin):
    sis.cadastros.criar_investidor(admin, nome="Diego", documento="000.111", login="diego",
                                   senha="Diego@Forte2026", saldo_inicial=Decimal("1000"))
    d = sis.autenticacao.iniciar_login("diego", "Diego@Forte2026")
    u, _ = sis.autenticacao.validar_mfa(d.desafio_id, sis.notificador.ultimo_codigo("diego"))
    assert Decimal(sis.ordens.carteira(u)["saldo"]) == Decimal("1000.00")


def test_login_duplicado_e_recusado(sis, admin):
    with pytest.raises((ConflitoError, RegraNegocioError)):
        sis.cadastros.criar_investidor(admin, nome="Outra Ana", documento="999", login="ana", senha="Ana@Forte20261x")


def test_investidor_inativo_nao_opera(sis, admin, ana):
    sis.cadastros.definir_situacao_investidor(admin, ana.investidor_id, False)
    with pytest.raises(SentinelTradeError):
        sis.ordens.enviar(ana, nova())


# ------------------------------------------------------------------ auditoria
def _acoes(sis, auditor):
    return [r["acao"] for r in sis.consultas.consultar_auditoria(auditor)]


def test_eventos_relevantes_sao_auditados(sis, ana, operador, auditor):
    sis.ordens.enviar(ana, nova())
    sis.ordens.enviar(ana, nova(qtd=1_000_000))                      # rejeitada
    with pytest.raises(AutenticacaoError):
        sis.autenticacao.iniciar_login("ana", "errada-errada-1")
    sis.risco.acionar_suspensao(operador, "MERCADO", "teste de auditoria")
    acoes = " ".join(_acoes(sis, auditor))
    for esperado in ("LOGIN", "ORDEM", "SUSPENS"):
        assert esperado in acoes


def test_auditoria_nao_registra_senha_nem_codigo_mfa(sis, ana, auditor):
    sis.ordens.enviar(ana, nova())
    bruto = str(sis.consultas.consultar_auditoria(auditor))
    assert seed.senha_demo() not in bruto


def test_cadeia_de_hash_integra_e_consulta_e_auditada(sis, ana, auditor):
    sis.ordens.enviar(ana, nova())
    r = sis.consultas.verificar_integridade(auditor)
    assert r["integra"] and r["total_verificado"] > 0
    assert "AUDITORIA_VERIFICADA" in _acoes(sis, auditor)


def test_auditoria_e_append_only_no_banco(sis, ana):
    sis.ordens.enviar(ana, nova())
    with pytest.raises(Exception):
        with sis.banco.engine.begin() as c:
            c.execute(text("update auditoria set usuario='fraude' where id=1"))
    with pytest.raises(Exception):
        with sis.banco.engine.begin() as c:
            c.execute(text("delete from auditoria"))


def test_adulteracao_e_detectada_pela_cadeia_de_hash(sis, ana, auditor):
    sis.ordens.enviar(ana, nova())
    with sis.banco.engine.begin() as c:                              # atacante com acesso direto remove o gatilho
        c.execute(text("DROP TRIGGER auditoria_sem_update"))
        c.execute(text("update auditoria set usuario='fraude' where id=2"))
    r = sis.consultas.verificar_integridade(auditor)
    assert r["integra"] is False and 2 in r["registros_suspeitos"]


# ------------------------------------------------------------------ cadastros (CSU09–CSU11)
def test_admin_deposita_e_cria_ativo(sis, admin):
    inv = sis.cadastros.listar_investidores(admin)[0]
    antes = Decimal(inv["saldo"])
    sis.cadastros.depositar(admin, inv["id"], Decimal("250.50"))
    depois = next(i for i in sis.cadastros.listar_investidores(admin) if i["id"] == inv["id"])
    assert Decimal(depois["saldo"]) == antes + Decimal("250.50")
    with pytest.raises(SentinelTradeError):
        sis.cadastros.depositar(admin, inv["id"], Decimal("-1"))
    sis.cadastros.criar_ativo(admin, codigo="TEST3", nome="Empresa Teste", tipo="ACAO", lote_padrao=100,
                              preco_inicial=Decimal("10.00"))
    assert any(a["codigo"] == "TEST3" for a in sis.cadastros.listar_ativos(admin))
    with pytest.raises(SentinelTradeError):                                   # código duplicado
        sis.cadastros.criar_ativo(admin, codigo="TEST3", nome="Outra", tipo="ACAO", lote_padrao=100,
                                  preco_inicial=Decimal("10.00"))


def test_ativo_suspenso_nao_aceita_ordens(sis, admin, ana):
    sis.cadastros.atualizar_ativo(admin, "PETR4", situacao="SUSPENSO")
    assert sis.ordens.enviar(ana, nova())["estado"] == "REJEITADA"     # RN04: ativo não negociável


def test_admin_altera_perfil_e_desbloqueia_usuario(sis, admin):
    op = next(u for u in sis.cadastros.listar_usuarios(admin) if u["login"] == "operador")
    sis.cadastros.alterar_perfil(admin, op["id"], "AUDITOR")
    assert next(u for u in sis.cadastros.listar_usuarios(admin) if u["id"] == op["id"])["perfil"] == "AUDITOR"
    with pytest.raises(SentinelTradeError):
        sis.cadastros.alterar_perfil(admin, op["id"], "ADMINISTRADOR")
    for _ in range(sis.config.mfa_max_tentativas):
        try:
            sis.autenticacao.iniciar_login("operador", "errada-errada-1")
        except SentinelTradeError:
            pass
    assert next(u for u in sis.cadastros.listar_usuarios(admin) if u["id"] == op["id"])["bloqueado"] is True
    sis.cadastros.definir_situacao_usuario(admin, op["id"], desbloquear=True)
    assert next(u for u in sis.cadastros.listar_usuarios(admin) if u["id"] == op["id"])["bloqueado"] is False


def test_investidor_com_ordem_ativa_nao_pode_ser_desativado(sis, admin, ana):
    preco = (sis.provedor.ultimo_preco("VALE3") * Decimal("0.95")).quantize(Decimal("0.01"))
    sis.ordens.enviar(ana, nova(ativo="VALE3", modalidade="LIMITADA", preco=preco)); sis.tick()
    with pytest.raises(ConflitoError):
        sis.cadastros.definir_situacao_investidor(admin, ana.investidor_id, False)
