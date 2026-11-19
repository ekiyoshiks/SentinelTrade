"""Aplicação FastAPI: tratamento seguro de erros (RNF-06) e entrega do dashboard."""
from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import Configuracoes
from ..dominio.excecoes import SentinelTradeError
from ..servicos.sistema import Sistema
from .rotas import router

log = logging.getLogger("sentineltrade")
ESTATICOS = Path(__file__).resolve().parent.parent / "dashboard" / "static"


def criar_app(sistema: Sistema | None = None, *, iniciar_worker: bool = True,
              popular_se_vazio: bool = True) -> FastAPI:
    sistema = sistema or Sistema(Configuracoes.de_ambiente())

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI):
        sistema.banco.criar_tabelas()
        if popular_se_vazio and sistema.config.modo_simulacao:
            from ..seed import popular
            from ..persistencia.repositorios import RepositorioUsuarios
            with sistema.banco.transacao() as s:
                vazio = not RepositorioUsuarios(s).listar()
            if vazio:
                popular(sistema)
        worker = sistema.iniciar_worker() if iniciar_worker else None
        yield
        if worker:
            worker.parar()

    app = FastAPI(title="SentinelTrade", version="0.2.0", lifespan=ciclo_de_vida,
                  docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.sistema = sistema

    @app.exception_handler(SentinelTradeError)
    async def erro_de_dominio(_: Request, erro: SentinelTradeError):
        return JSONResponse(status_code=erro.status_http, content={
            "erro": {"codigo": erro.codigo, "mensagem": erro.mensagem, "detalhes": erro.detalhes}})

    @app.exception_handler(RequestValidationError)
    async def erro_de_entrada(_: Request, erro: RequestValidationError):
        # só campo e motivo — nunca ecoa o valor recebido nem detalhes internos
        campos = [{"campo": ".".join(str(p) for p in e["loc"] if p != "body"), "motivo": e["msg"]}
                  for e in erro.errors()]
        return JSONResponse(status_code=422, content={"erro": {
            "codigo": "ENTRADA_INVALIDA", "mensagem": "Dados inválidos.", "detalhes": {"campos": campos}}})

    @app.exception_handler(Exception)
    async def erro_inesperado(_: Request, erro: Exception):
        referencia = uuid.uuid4().hex[:8]
        log.exception("Erro interno [%s]", referencia)   # detalhe técnico só no log protegido
        return JSONResponse(status_code=500, content={"erro": {
            "codigo": "ERRO_INTERNO", "mensagem": "Erro interno. Informe a referência ao suporte.",
            "detalhes": {"referencia": referencia}}})

    app.include_router(router)
    if ESTATICOS.is_dir():
        app.mount("/", StaticFiles(directory=ESTATICOS, html=True), name="dashboard")
    return app


def app_padrao() -> FastAPI:
    """Fábrica usada pelo uvicorn: ``uvicorn sentineltrade.api.app:app_padrao --factory``."""
    return criar_app()
