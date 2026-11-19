"""Dependências das rotas: sistema, usuário autenticado e autorização por perfil (RNF-03)."""
from __future__ import annotations

from typing import Callable

from fastapi import Depends, Request

from ..dominio.excecoes import AcessoNegadoError, AutenticacaoError
from ..dominio.usuarios import Usuario
from ..servicos.sistema import Sistema

COOKIE_SESSAO = "st_sessao"


def obter_sistema(request: Request) -> Sistema:
    return request.app.state.sistema


def _token(request: Request) -> str | None:
    cabecalho = request.headers.get("authorization", "")
    if cabecalho.lower().startswith("bearer "):
        return cabecalho[7:].strip()
    return request.cookies.get(COOKIE_SESSAO)


def usuario_atual(request: Request, sistema: Sistema = Depends(obter_sistema)) -> Usuario:
    token = _token(request)
    if not token:
        raise AutenticacaoError("Autenticação necessária.", codigo="NAO_AUTENTICADO")
    return sistema.autenticacao.usuario_do_token(token)


def exigir(permissao: str) -> Callable[[Usuario], Usuario]:
    """Autoriza a requisição no servidor, conforme o perfil (princípio do menor privilégio)."""
    def dependencia(usuario: Usuario = Depends(usuario_atual)) -> Usuario:
        if not usuario.pode(permissao):
            raise AcessoNegadoError("Seu perfil não tem permissão para esta operação.")
        return usuario
    return dependencia


def origem(request: Request) -> str:
    return f"api:{request.client.host if request.client else 'desconhecido'}"
