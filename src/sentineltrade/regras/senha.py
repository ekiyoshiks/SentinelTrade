"""RN10 (política de senha) e hash de senha com Argon2 (RNF-01)."""
from __future__ import annotations

import re

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from ..dominio.excecoes import RegraNegocioError
from ..dominio.usuarios import HashSenha


class RN10PoliticaSenha:
    """Mínimo de 12 caracteres, combinando letras e números (RN10)."""

    codigo = "RN10"
    descricao = "A senha deve ter no mínimo 12 caracteres, combinando letras e números."
    MINIMO = 12

    def validar_senha(self, senha: str) -> None:
        if (len(senha) < self.MINIMO or not re.search(r"[A-Za-z]", senha)
                or not re.search(r"\d", senha)):
            raise RegraNegocioError(self.descricao, codigo=self.codigo)


class HashArgon2(HashSenha):
    def __init__(self) -> None:
        self._ph = PasswordHasher()

    def gerar(self, senha: str) -> str:
        return self._ph.hash(senha)

    def verificar(self, hash_armazenado: str, senha: str) -> bool:
        try:
            return self._ph.verify(hash_armazenado, senha)
        except (VerifyMismatchError, InvalidHashError):
            return False
