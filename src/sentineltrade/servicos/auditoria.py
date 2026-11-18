"""Auditoria imutável com encadeamento por hash (RF-17, RN12, RNF-18, RNF-20).

Cada registro guarda o hash do anterior; alterar ou apagar um registro quebra a cadeia e a
verificação de integridade (CSU14, passo 6) aponta onde. Os registros nunca contêm senhas,
tokens nem códigos (RNF-19).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..dominio.relogio import Relogio
from ..persistencia.mapeamento import RegistroAuditoria
from ..persistencia.repositorios import RepositorioAuditoria

GENESIS = "0" * 64
_CHAVES_PROIBIDAS = {"senha", "token", "codigo", "codigo_mfa", "segredo", "hash"}


@dataclass
class ResultadoIntegridade:
    integra: bool
    total_verificado: int
    registros_suspeitos: list[int]


def _limpar(detalhes: dict | None) -> dict:
    """Remove campos sensíveis dos detalhes antes de gravar (RNF-19)."""
    if not detalhes:
        return {}
    return {k: ("***" if k.lower() in _CHAVES_PROIBIDAS else v) for k, v in detalhes.items()}


def _calcular_hash(anterior: str, campos: dict) -> str:
    canonico = json.dumps(campos, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256((anterior + canonico).encode("utf-8")).hexdigest()


def _campos(r: RegistroAuditoria) -> dict:
    ocorrido = r.ocorrido_em
    return {
        "ocorrido_em": ocorrido.isoformat(timespec="microseconds") if isinstance(ocorrido, datetime) else str(ocorrido),
        "usuario": r.usuario, "perfil": r.perfil, "acao": r.acao, "entidade": r.entidade,
        "entidade_id": r.entidade_id, "resultado": r.resultado, "origem": r.origem,
        "correlacao_id": r.correlacao_id, "detalhes": r.detalhes,
    }


class AuditoriaService:
    def __init__(self, relogio: Relogio):
        self._relogio = relogio

    def registrar(self, s: Session, *, usuario: str, acao: str, perfil: str | None = None,
                  entidade: str | None = None, entidade_id: str | None = None,
                  resultado: str = "SUCESSO", origem: str | None = None,
                  correlacao_id: str | None = None, detalhes: dict | None = None) -> RegistroAuditoria:
        """Acrescenta um registro à cadeia. Deve ser chamado dentro da transação do caso de uso."""
        s.flush()
        anterior = s.scalar(select(RegistroAuditoria.hash).order_by(RegistroAuditoria.id.desc()).limit(1))
        anterior = anterior or GENESIS
        registro = RegistroAuditoria(
            ocorrido_em=self._relogio.agora(), usuario=usuario, perfil=perfil, acao=acao,
            entidade=entidade, entidade_id=entidade_id, resultado=resultado, origem=origem,
            correlacao_id=correlacao_id,
            detalhes=json.dumps(_limpar(detalhes), ensure_ascii=False, sort_keys=True, default=str),
            hash_anterior=anterior, hash="")
        registro.hash = _calcular_hash(anterior, _campos(registro))
        s.add(registro)
        s.flush()
        return registro

    def consultar(self, s: Session, **filtros) -> list[RegistroAuditoria]:
        return RepositorioAuditoria(s).consultar(**filtros)

    def verificar_integridade(self, s: Session, desde: datetime | None = None,
                              ate: datetime | None = None) -> ResultadoIntegridade:
        """Recalcula a cadeia inteira e informa registros cujo hash ou elo não conferem."""
        esperado = GENESIS
        suspeitos: list[int] = []
        total = 0
        for r in s.scalars(select(RegistroAuditoria).order_by(RegistroAuditoria.id)):
            no_periodo = (desde is None or r.ocorrido_em >= desde) and (ate is None or r.ocorrido_em <= ate)
            invalido = r.hash_anterior != esperado or r.hash != _calcular_hash(r.hash_anterior, _campos(r))
            if no_periodo:
                total += 1
                if invalido:
                    suspeitos.append(r.id)
            esperado = r.hash
        return ResultadoIntegridade(integra=not suspeitos, total_verificado=total, registros_suspeitos=suspeitos)
