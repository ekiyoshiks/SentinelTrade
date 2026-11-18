"""Hierarquia de exceções do sistema (RNF-06: erros tratados sem expor detalhes internos).

Cada exceção carrega um código estável e uma mensagem segura para o usuário. O detalhe
técnico (stack trace, SQL) vai apenas para o log protegido.
"""
from __future__ import annotations


class SentinelTradeError(Exception):
    """Base de todas as exceções esperadas do sistema."""

    codigo = "ERRO"
    status_http = 400

    def __init__(self, mensagem: str, *, codigo: str | None = None, detalhes: dict | None = None):
        super().__init__(mensagem)
        self.mensagem = mensagem
        if codigo is not None:
            self.codigo = codigo
        self.detalhes = detalhes or {}


class ValidacaoEntradaError(SentinelTradeError):
    codigo = "ENTRADA_INVALIDA"
    status_http = 422


class RegraNegocioError(SentinelTradeError):
    """Violação de uma regra de negócio (RNxx).

    ``rejeita_ordem`` indica se, no CSU04, a ordem fica registrada no estado Rejeitada
    (saldo, limite, mercado) ou se o fluxo apenas volta ao passo 1 (lote, preço, cotação).
    """

    codigo = "REGRA_NEGOCIO"
    status_http = 422

    def __init__(self, mensagem: str, *, codigo: str | None = None, rejeita_ordem: bool = False,
                 detalhes: dict | None = None):
        super().__init__(mensagem, codigo=codigo, detalhes=detalhes)
        self.rejeita_ordem = rejeita_ordem


class TransicaoInvalidaError(RegraNegocioError):
    codigo = "RN09"


class AutenticacaoError(SentinelTradeError):
    codigo = "AUTENTICACAO"
    status_http = 401


class ContaBloqueadaError(SentinelTradeError):
    codigo = "RN11"
    status_http = 423


class AcessoNegadoError(SentinelTradeError):
    codigo = "ACESSO_NEGADO"
    status_http = 403


class NaoEncontradoError(SentinelTradeError):
    codigo = "NAO_ENCONTRADO"
    status_http = 404


class ConflitoError(SentinelTradeError):
    codigo = "CONFLITO"
    status_http = 409


class IndisponibilidadeSeguraError(SentinelTradeError):
    codigo = "INDISPONIBILIDADE_SEGURA"
    status_http = 503


class IntegracaoError(SentinelTradeError):
    codigo = "INTEGRACAO"
    status_http = 502


class IntegracaoTimeoutError(IntegracaoError):
    codigo = "INTEGRACAO_TIMEOUT"
    status_http = 504


class BolsaRecusouError(ConflitoError):
    """A Bolsa recusou alterar/cancelar (ex.: a ordem já foi executada)."""

    codigo = "BOLSA_RECUSOU"
