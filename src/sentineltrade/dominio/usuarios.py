"""Usuários e perfis de acesso.

``Usuario`` é uma classe abstrata (abstração); cada perfil é uma subclasse (herança) que
declara suas próprias permissões. O hash da senha e o contador de falhas são privados
(encapsulamento, RNF-04) e só mudam por métodos que aplicam RN10/RN11.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from enum import Enum
from typing import ClassVar


class Perfil(str, Enum):
    INVESTIDOR = "INVESTIDOR"
    OPERADOR_RISCO = "OPERADOR_RISCO"
    ADMINISTRADOR = "ADMINISTRADOR"
    AUDITOR = "AUDITOR"


class HashSenha(ABC):
    """Contrato do algoritmo de hash de senha (RNF-01)."""

    @abstractmethod
    def gerar(self, senha: str) -> str: ...

    @abstractmethod
    def verificar(self, hash_armazenado: str, senha: str) -> bool: ...


class Usuario(ABC):
    PERFIL: ClassVar[Perfil]
    PERMISSOES: ClassVar[frozenset[str]]

    def __init__(self, login: str, senha_hash: str, *, investidor_id: int | None = None):
        self.login = login
        self._senha_hash = senha_hash
        self._ativo = True
        self._tentativas_falhas = 0
        self._bloqueado_ate: datetime | None = None
        self.investidor_id = investidor_id

    # --- leitura -----------------------------------------------------------
    @property
    def perfil(self) -> Perfil:
        return self.PERFIL

    @property
    def ativo(self) -> bool:
        return bool(self._ativo)

    @property
    def tentativas_falhas(self) -> int:
        return self._tentativas_falhas

    @property
    def bloqueado_ate(self) -> datetime | None:
        return self._bloqueado_ate

    def pode(self, permissao: str) -> bool:
        return permissao in self.PERMISSOES

    # --- senha e bloqueio --------------------------------------------------
    def verificar_senha(self, senha: str, hasher: HashSenha) -> bool:
        return hasher.verificar(self._senha_hash, senha)

    def definir_senha_hash(self, novo_hash: str) -> None:
        self._senha_hash = novo_hash

    def esta_bloqueado(self, agora: datetime) -> bool:
        return self._bloqueado_ate is not None and self._bloqueado_ate > agora

    def registrar_falha(self, agora: datetime, max_tentativas: int, bloqueio_minutos: int) -> bool:
        """Registra tentativa inválida (RN11). Retorna True se a conta foi bloqueada agora."""
        if self._bloqueado_ate is not None and self._bloqueado_ate <= agora:
            self._bloqueado_ate = None
            self._tentativas_falhas = 0
        self._tentativas_falhas += 1
        if self._tentativas_falhas >= max_tentativas:
            self._bloqueado_ate = agora + timedelta(minutes=bloqueio_minutos)
            self._tentativas_falhas = 0
            return True
        return False

    def registrar_sucesso(self) -> None:
        self._tentativas_falhas = 0
        self._bloqueado_ate = None

    def desbloquear(self) -> None:
        self.registrar_sucesso()

    def desativar(self) -> None:
        self._ativo = False

    def reativar(self) -> None:
        self._ativo = True

    @abstractmethod
    def descricao_perfil(self) -> str:
        """Nome amigável do perfil, usado na interface."""


class UsuarioInvestidor(Usuario):
    PERFIL = Perfil.INVESTIDOR
    PERMISSOES = frozenset({
        "cotacao:ver", "carteira:ver", "ordem:enviar", "ordem:alterar",
        "ordem:cancelar", "ordem:ver", "historico:ver", "notificacao:ver",
    })

    def descricao_perfil(self) -> str:
        return "Investidor"


class UsuarioOperadorRisco(Usuario):
    PERFIL = Perfil.OPERADOR_RISCO
    PERMISSOES = frozenset({
        "cotacao:ver", "limite:definir", "suspensao:acionar", "painel:ver",
        "ordem:ver_todas", "simulacao:operar", "notificacao:ver",
    })

    def descricao_perfil(self) -> str:
        return "Operador de Risco"


class UsuarioAdministrador(Usuario):
    PERFIL = Perfil.ADMINISTRADOR
    PERMISSOES = frozenset({
        "cotacao:ver", "cadastro:investidor", "cadastro:ativo", "perfil:gerenciar",
        "painel:ver", "ordem:ver_todas",
    })

    def descricao_perfil(self) -> str:
        return "Administrador"


class UsuarioAuditor(Usuario):
    PERFIL = Perfil.AUDITOR
    PERMISSOES = frozenset({"cotacao:ver", "auditoria:consultar", "painel:ver", "ordem:ver_todas"})

    def descricao_perfil(self) -> str:
        return "Auditor"


CLASSES_POR_PERFIL: dict[Perfil, type[Usuario]] = {
    Perfil.INVESTIDOR: UsuarioInvestidor,
    Perfil.OPERADOR_RISCO: UsuarioOperadorRisco,
    Perfil.ADMINISTRADOR: UsuarioAdministrador,
    Perfil.AUDITOR: UsuarioAuditor,
}


def criar_usuario(perfil: Perfil, login: str, senha_hash: str, *, investidor_id: int | None = None) -> Usuario:
    """Fábrica: devolve a subclasse correta para o perfil."""
    return CLASSES_POR_PERFIL[perfil](login, senha_hash, investidor_id=investidor_id)


class CadastroInvestidor:
    """Pessoa cadastrada na corretora (RF-03). Um usuário INVESTIDOR aponta para este cadastro."""

    def __init__(self, nome: str, documento: str):
        self.nome = nome
        self.documento = documento
        self._ativo = True

    @property
    def ativo(self) -> bool:
        return bool(self._ativo)

    def desativar(self) -> None:
        self._ativo = False

    def reativar(self) -> None:
        self._ativo = True
