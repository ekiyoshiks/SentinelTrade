"""O DDL versionado em db/ deve refletir o modelo; o schema SQLite deve ser executável do zero."""
import sqlite3
from pathlib import Path

from sentineltrade.persistencia.banco import gerar_ddl
from sentineltrade.persistencia.tabelas import metadata

DB = Path(__file__).resolve().parent.parent / "db"


def test_schema_versionado_esta_atualizado():
    assert (DB / "schema.sqlite.sql").read_text() == gerar_ddl("sqlite"), "rode: python -m sentineltrade.cli export-schema"
    assert (DB / "schema.postgresql.sql").read_text() == gerar_ddl("postgresql")


def test_schema_sqlite_executa_e_cria_todas_as_tabelas():
    c = sqlite3.connect(":memory:")
    c.executescript((DB / "schema.sqlite.sql").read_text())
    tabelas = {r[0] for r in c.execute("select name from sqlite_master where type='table'")}
    assert set(metadata.tables) <= tabelas


def test_restricoes_do_banco_barram_dados_invalidos():
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON")
    c.executescript((DB / "schema.sqlite.sql").read_text())
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("insert into ativos (codigo,nome,tipo,lote_padrao,situacao) values ('X','x','INVALIDO',100,'NEGOCIAVEL')")
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("insert into ativos (codigo,nome,tipo,lote_padrao,situacao) values ('X','x','ACAO',0,'NEGOCIAVEL')")
