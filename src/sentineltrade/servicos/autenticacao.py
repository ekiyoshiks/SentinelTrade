"""CSU01 — Autenticar com MFA.

Fluxo em duas etapas: (1) login + senha → desafio com código de uso único enviado pelo
Serviço de Notificação (segundo fator simulado, válido por 60 s — RNF-02); (2) código →
sessão assinada. Falhas consecutivas bloqueiam a conta por 15 min (RN11). Toda tentativa é
auditada. A mensagem de erro nunca revela qual dado estava errado.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from itsdangerous import BadSignature, URLSafeTimedSerializer

from ..config import Configuracoes
from ..dominio.excecoes import AutenticacaoError, ContaBloqueadaError, SentinelTradeError
from ..dominio.relogio import Relogio
from ..dominio.usuarios import HashSenha, Usuario
from ..integracoes.interfaces import Notificador
from ..persistencia.banco import Banco
from ..persistencia.mapeamento import DesafioMfa
from ..persistencia.repositorios import RepositorioUsuarios
from ..regras.senha import RN10PoliticaSenha
from .auditoria import AuditoriaService

MSG_CREDENCIAIS = "Credenciais inválidas."


@dataclass
class DesafioMfaInfo:
    desafio_id: str
    expira_em: datetime
    validade_segundos: int


def _hash_codigo(desafio_id: str, codigo: str) -> str:
    return hashlib.sha256(f"{desafio_id}:{codigo}".encode()).hexdigest()


class AutenticacaoService:
    def __init__(self, banco: Banco, relogio: Relogio, config: Configuracoes, hasher: HashSenha,
                 notificador: Notificador, auditoria: AuditoriaService):
        self._banco, self._relogio, self._config = banco, relogio, config
        self._hasher, self._notificador, self._auditoria = hasher, notificador, auditoria
        self._politica = RN10PoliticaSenha()
        self._serializador = URLSafeTimedSerializer(config.jwt_secret, salt="sentineltrade-sessao")
        # hash fictício para igualar o tempo de resposta quando o login não existe
        self._hash_fantasma = hasher.gerar("fantasma-Senha-0000")

    # ------------------------------------------------------------------ etapa 1
    def iniciar_login(self, login: str, senha: str, origem: str = "API") -> DesafioMfaInfo:
        erro: SentinelTradeError | None = None
        resultado: DesafioMfaInfo | None = None
        codigo_a_enviar: tuple[str, str] | None = None
        agora = self._relogio.agora()
        with self._banco.exclusivo():
            with self._banco.transacao() as s:
                usuario = RepositorioUsuarios(s).por_login(login)
                if usuario is None or not usuario.ativo:
                    self._hasher.verificar(self._hash_fantasma, senha)
                    self._auditoria.registrar(s, usuario=login or "?", acao="LOGIN_SENHA", resultado="FALHA",
                                              origem=origem, detalhes={"motivo": "usuario_invalido"})
                    erro = AutenticacaoError(MSG_CREDENCIAIS)
                elif usuario.esta_bloqueado(agora):
                    self._auditoria.registrar(s, usuario=login, perfil=usuario.perfil.value, acao="LOGIN_SENHA",
                                              resultado="BLOQUEADO", origem=origem)
                    erro = ContaBloqueadaError("Conta bloqueada temporariamente. Tente novamente mais tarde.")
                elif not usuario.verificar_senha(senha, self._hasher):
                    bloqueou = usuario.registrar_falha(agora, self._config.mfa_max_tentativas,
                                                       self._config.bloqueio_minutos)
                    self._auditoria.registrar(s, usuario=login, perfil=usuario.perfil.value, acao="LOGIN_SENHA",
                                              resultado="FALHA", origem=origem,
                                              detalhes={"bloqueou_conta": bloqueou})
                    erro = (ContaBloqueadaError("Conta bloqueada temporariamente. Tente novamente mais tarde.")
                            if bloqueou else AutenticacaoError(MSG_CREDENCIAIS))
                else:
                    desafio_id = str(uuid.uuid4())
                    codigo = f"{secrets.randbelow(1_000_000):06d}"
                    expira = agora + timedelta(seconds=self._config.mfa_validade_segundos)
                    s.add(DesafioMfa(id=desafio_id, usuario_id=usuario.id,
                                     codigo_hash=_hash_codigo(desafio_id, codigo),
                                     expira_em=expira, usado=False, criado_em=agora))
                    self._auditoria.registrar(s, usuario=login, perfil=usuario.perfil.value,
                                              acao="LOGIN_SENHA", origem=origem)
                    resultado = DesafioMfaInfo(desafio_id, expira, self._config.mfa_validade_segundos)
                    codigo_a_enviar = (login, codigo)
        if erro:
            raise erro
        assert resultado and codigo_a_enviar
        self._notificador.enviar_codigo_mfa(*codigo_a_enviar)
        return resultado

    def reenviar_codigo(self, desafio_id: str, origem: str = "API") -> DesafioMfaInfo:
        """Fluxo alternativo do CSU01: segundo fator expirado → emite novo código."""
        agora = self._relogio.agora()
        with self._banco.exclusivo():
            with self._banco.transacao() as s:
                desafio = s.get(DesafioMfa, desafio_id)
                usuario = RepositorioUsuarios(s).por_id(desafio.usuario_id) if desafio else None
                if desafio is None or desafio.usado or usuario is None or not usuario.ativo:
                    raise AutenticacaoError("Desafio inválido. Faça login novamente.")
                if usuario.esta_bloqueado(agora):
                    raise ContaBloqueadaError("Conta bloqueada temporariamente. Tente novamente mais tarde.")
                codigo = f"{secrets.randbelow(1_000_000):06d}"
                desafio.codigo_hash = _hash_codigo(desafio_id, codigo)
                desafio.expira_em = agora + timedelta(seconds=self._config.mfa_validade_segundos)
                self._auditoria.registrar(s, usuario=usuario.login, perfil=usuario.perfil.value,
                                          acao="MFA_NOVO_CODIGO", origem=origem)
                login, expira = usuario.login, desafio.expira_em
        self._notificador.enviar_codigo_mfa(login, codigo)
        return DesafioMfaInfo(desafio_id, expira, self._config.mfa_validade_segundos)

    # ------------------------------------------------------------------ etapa 2
    def validar_mfa(self, desafio_id: str, codigo: str, origem: str = "API") -> tuple[Usuario, str]:
        erro: SentinelTradeError | None = None
        usuario_ok: Usuario | None = None
        agora = self._relogio.agora()
        with self._banco.exclusivo():
            with self._banco.transacao() as s:
                desafio = s.get(DesafioMfa, desafio_id)
                usuario = RepositorioUsuarios(s).por_id(desafio.usuario_id) if desafio else None
                if desafio is None or desafio.usado or usuario is None or not usuario.ativo:
                    erro = AutenticacaoError(MSG_CREDENCIAIS)
                elif usuario.esta_bloqueado(agora):
                    erro = ContaBloqueadaError("Conta bloqueada temporariamente. Tente novamente mais tarde.")
                elif desafio.expira_em < agora:
                    self._auditoria.registrar(s, usuario=usuario.login, perfil=usuario.perfil.value,
                                              acao="LOGIN_MFA", resultado="EXPIRADO", origem=origem)
                    erro = AutenticacaoError("Código expirado. Solicite um novo código.", codigo="MFA_EXPIRADO")
                elif not hmac.compare_digest(desafio.codigo_hash, _hash_codigo(desafio_id, codigo.strip())):
                    bloqueou = usuario.registrar_falha(agora, self._config.mfa_max_tentativas,
                                                       self._config.bloqueio_minutos)
                    self._auditoria.registrar(s, usuario=usuario.login, perfil=usuario.perfil.value,
                                              acao="LOGIN_MFA", resultado="FALHA", origem=origem,
                                              detalhes={"bloqueou_conta": bloqueou})
                    erro = (ContaBloqueadaError("Conta bloqueada temporariamente. Tente novamente mais tarde.")
                            if bloqueou else AutenticacaoError("Código inválido.", codigo="MFA_INVALIDO"))
                else:
                    desafio.usado = True
                    usuario.registrar_sucesso()
                    self._auditoria.registrar(s, usuario=usuario.login, perfil=usuario.perfil.value,
                                              acao="LOGIN_MFA", origem=origem)
                    usuario_ok = usuario
        if erro:
            raise erro
        assert usuario_ok
        return usuario_ok, self.emitir_token(usuario_ok)

    # ------------------------------------------------------------------ sessão
    def emitir_token(self, usuario: Usuario) -> str:
        return self._serializador.dumps({"uid": usuario.id, "iat": self._relogio.agora().timestamp()})

    def usuario_do_token(self, token: str) -> Usuario:
        try:
            dados = self._serializador.loads(token)
            idade = self._relogio.agora().timestamp() - float(dados["iat"])   # relógio injetável (testes)
        except (BadSignature, KeyError, TypeError, ValueError):
            raise AutenticacaoError("Sessão inválida.")
        if idade > self._config.sessao_validade_segundos:
            raise AutenticacaoError("Sessão expirada. Faça login novamente.", codigo="SESSAO_EXPIRADA")
        with self._banco.transacao() as s:
            usuario = RepositorioUsuarios(s).por_id(dados["uid"])
        if usuario is None or not usuario.ativo or usuario.esta_bloqueado(self._relogio.agora()):
            raise AutenticacaoError("Sessão inválida.")
        return usuario

    def encerrar_sessao(self, usuario: Usuario, origem: str = "API") -> None:
        with self._banco.exclusivo(), self._banco.transacao() as s:
            self._auditoria.registrar(s, usuario=usuario.login, perfil=usuario.perfil.value,
                                      acao="LOGOUT", origem=origem)

    # ------------------------------------------------------------------ senha
    def gerar_hash_senha(self, senha: str) -> str:
        """Aplica RN10 e devolve o hash Argon2 (nunca a senha)."""
        self._politica.validar_senha(senha)
        return self._hasher.gerar(senha)
