"""Conexão com o banco, criação do esquema e unidade de trabalho (transação).

Escrita serializada: todas as transações passam por um lock de processo. Isso mantém a
cadeia de hash da auditoria linear e dispensa ``SELECT ... FOR UPDATE`` em SQLite. Para
rodar com várias instâncias em PostgreSQL, trocar o lock por ``pg_advisory_xact_lock``.
"""
from __future__ import annotations

import threading
import warnings
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from . import mapeamento  # noqa: F401  (garante o mapeamento ORM)
from .tabelas import metadata

warnings.filterwarnings("ignore", message=".*does \\*not\\* support Decimal.*")

_TRIGGERS_SQLITE = [
    """CREATE TRIGGER IF NOT EXISTS auditoria_sem_update BEFORE UPDATE ON auditoria
       BEGIN SELECT RAISE(ABORT, 'RN12: auditoria e append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS auditoria_sem_delete BEFORE DELETE ON auditoria
       BEGIN SELECT RAISE(ABORT, 'RN12: auditoria e append-only'); END""",
]

_TRIGGERS_POSTGRES = [
    """CREATE OR REPLACE FUNCTION auditoria_imutavel() RETURNS trigger AS $$
       BEGIN RAISE EXCEPTION 'RN12: auditoria e append-only'; END; $$ LANGUAGE plpgsql""",
    "DROP TRIGGER IF EXISTS auditoria_sem_alteracao ON auditoria",
    """CREATE TRIGGER auditoria_sem_alteracao BEFORE UPDATE OR DELETE ON auditoria
       FOR EACH ROW EXECUTE FUNCTION auditoria_imutavel()""",
]


class Banco:
    def __init__(self, url: str):
        self.url = url
        self.engine = self._criar_engine(url)
        self._fabrica = sessionmaker(self.engine, expire_on_commit=False, autoflush=True)
        self._lock = threading.RLock()

    @staticmethod
    def _criar_engine(url: str) -> Engine:
        if url.startswith("sqlite"):
            memoria = url in ("sqlite://", "sqlite:///:memory:")
            if not memoria and url.startswith("sqlite:///"):
                import os
                pasta = os.path.dirname(url.replace("sqlite:///", "", 1))
                if pasta:
                    os.makedirs(pasta, exist_ok=True)
            kwargs = {"connect_args": {"check_same_thread": False, "timeout": 30}}
            if memoria:
                kwargs["poolclass"] = StaticPool
            engine = create_engine(url, **kwargs)

            @event.listens_for(engine, "connect")
            def _pragmas(conexao, _):
                cur = conexao.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                if not memoria:
                    cur.execute("PRAGMA journal_mode=WAL")
                cur.close()
            return engine
        return create_engine(url, pool_pre_ping=True)

    # --- esquema -----------------------------------------------------------
    def criar_tabelas(self) -> None:
        metadata.create_all(self.engine)
        comandos = _TRIGGERS_SQLITE if self.engine.dialect.name == "sqlite" else (
            _TRIGGERS_POSTGRES if self.engine.dialect.name == "postgresql" else [])
        with self.engine.begin() as conexao:
            for comando in comandos:
                conexao.execute(text(comando))

    def apagar_tudo(self) -> None:
        with self.engine.begin() as conexao:
            if self.engine.dialect.name == "sqlite":
                conexao.execute(text("DROP TRIGGER IF EXISTS auditoria_sem_update"))
                conexao.execute(text("DROP TRIGGER IF EXISTS auditoria_sem_delete"))
        metadata.drop_all(self.engine)

    # --- transação ---------------------------------------------------------
    @contextmanager
    def exclusivo(self) -> Iterator[None]:
        """Seção crítica de um caso de uso (várias transações em sequência, sem intercalação)."""
        with self._lock:
            yield

    @contextmanager
    def transacao(self) -> Iterator[Session]:
        """Transação "tudo ou nada" (RNF-17). Confirma ao sair; reverte em qualquer exceção."""
        with self._lock:
            sessao = self._fabrica()
            try:
                yield sessao
                sessao.commit()
            except BaseException:
                sessao.rollback()
                raise
            finally:
                sessao.close()

    def saudavel(self) -> bool:
        try:
            with self.engine.connect() as conexao:
                conexao.execute(text("SELECT 1"))
            return True
        except Exception:
            return False


def gerar_ddl(dialeto: str = "sqlite") -> str:
    """DDL completo (tabelas, índices e gatilhos de imutabilidade da auditoria) para o dialeto informado."""
    from sqlalchemy.dialects import postgresql, sqlite
    from sqlalchemy.schema import CreateIndex, CreateTable

    d = {"sqlite": sqlite.dialect(), "postgresql": postgresql.dialect()}[dialeto]
    partes = []
    for tabela in metadata.sorted_tables:
        partes.append(str(CreateTable(tabela).compile(dialect=d)).strip() + ";")
        partes.extend(str(CreateIndex(i).compile(dialect=d)).strip() + ";" for i in sorted(tabela.indexes, key=lambda x: x.name))
    gatilhos = _TRIGGERS_SQLITE if dialeto == "sqlite" else _TRIGGERS_POSTGRES
    partes.extend(" ".join(g.split()).replace("BEGIN", "BEGIN").strip() + ";" for g in gatilhos)
    return "\n\n".join(partes) + "\n"
