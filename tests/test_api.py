"""Camada HTTP: autenticação por cookie, autorização no servidor, erros seguros, idempotência via cabeçalho."""
import pytest
from fastapi.testclient import TestClient

from sentineltrade import seed
from sentineltrade.api.app import criar_app
from sentineltrade.config import Configuracoes
from sentineltrade.servicos.sistema import Sistema

ORDEM = {"ativo": "PETR4", "lado": "COMPRA", "modalidade": "MERCADO", "quantidade": 100}


@pytest.fixture
def app_sis():
    sis = Sistema(Configuracoes(database_url="sqlite://", mercado_sempre_aberto=True))
    sis.banco.criar_tabelas()
    seed.popular(sis)
    return criar_app(sis, iniciar_worker=False, popular_se_vazio=False), sis


def logar(app, sis, login):
    c = TestClient(app)
    d = c.post("/api/auth/login", json={"login": login, "senha": seed.senha_demo()}).json()["desafio_id"]
    r = c.post("/api/auth/mfa", json={"desafio_id": d, "codigo": sis.notificador.ultimo_codigo(login)})
    assert r.status_code == 200
    return c


def test_rotas_protegidas_exigem_login(app_sis):
    with TestClient(app_sis[0]) as c:
        assert c.get("/api/carteira").status_code == 401
        assert c.post("/api/ordens", json=ORDEM).status_code == 401


def test_cookie_de_sessao_httponly_e_samesite(app_sis):
    app, sis = app_sis
    with TestClient(app) as c0:
        d = c0.post("/api/auth/login", json={"login": "ana", "senha": seed.senha_demo()}).json()["desafio_id"]
        r = c0.post("/api/auth/mfa", json={"desafio_id": d, "codigo": sis.notificador.ultimo_codigo("ana")})
        cookie = r.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie


def test_criar_ordem_201_e_duplicada_200(app_sis):
    app, sis = app_sis
    with logar(app, sis, "ana") as c:
        r1 = c.post("/api/ordens", json=ORDEM, headers={"Idempotency-Key": "abc"})
        r2 = c.post("/api/ordens", json=ORDEM, headers={"Idempotency-Key": "abc"})
        assert r1.status_code == 201 and r2.status_code == 200
        assert r1.json()["id"] == r2.json()["id"] and r2.json()["duplicada"] is True


def test_entrada_invalida_422_sem_vazar_detalhes_internos(app_sis):
    app, sis = app_sis
    with logar(app, sis, "ana") as c:
        r = c.post("/api/ordens", json={**ORDEM, "quantidade": -1})
        assert r.status_code == 422
        corpo = r.text
        assert "Traceback" not in corpo and "sqlalchemy" not in corpo.lower() and '"erro"' in corpo
        assert c.post("/api/ordens", json={"ativo": "X' OR 1=1 --", "lado": "COMPRA", "modalidade": "MERCADO",
                                           "quantidade": 100}).status_code in (400, 404, 422)


def test_perfil_sem_permissao_recebe_403(app_sis):
    app, sis = app_sis
    with logar(app, sis, "ana") as c:
        assert c.get("/api/painel").status_code == 403
        assert c.get("/api/admin/usuarios").status_code == 403
        assert c.post("/api/risco/suspensoes", json={"escopo": "MERCADO", "motivo": "x y z"}).status_code == 403
    with logar(app, sis, "operador") as c:
        assert c.post("/api/ordens", json=ORDEM).status_code == 403
    with logar(app, sis, "auditor") as c:
        assert c.get("/api/auditoria").status_code == 200
        assert c.post("/api/simulacao/ciclo").status_code == 403


def test_investidor_nao_le_ordem_de_outro(app_sis):
    app, sis = app_sis
    with logar(app, sis, "ana") as a, logar(app, sis, "bruno") as b:
        oid = a.post("/api/ordens", json=ORDEM).json()["id"]
        assert b.get(f"/api/ordens/{oid}").status_code in (403, 404)
        assert b.post(f"/api/ordens/{oid}/cancelar").status_code in (403, 404)


def test_suspensao_devolve_503_e_aparece_em_saude(app_sis):
    app, sis = app_sis
    with logar(app, sis, "operador") as op, logar(app, sis, "ana") as a:
        assert op.post("/api/risco/suspensoes", json={"escopo": "MERCADO", "motivo": "teste http"}).status_code == 201
        assert a.get("/api/saude").json()["novas_ordens_suspensas"] is True
        assert a.post("/api/ordens", json=ORDEM).status_code == 503
        op.post("/api/risco/suspensoes/encerrar", json={"escopo": "MERCADO"})
        assert a.post("/api/ordens", json=ORDEM).status_code == 201


def test_logout_invalida_cookie(app_sis):
    app, sis = app_sis
    with logar(app, sis, "ana") as c:
        assert c.get("/api/auth/eu").status_code == 200
        c.post("/api/auth/logout")
        assert c.get("/api/carteira").status_code == 401


def test_dashboard_estatico_servido(app_sis):
    with TestClient(app_sis[0]) as c:
        assert c.get("/").status_code == 200 and c.get("/app.js").status_code == 200
