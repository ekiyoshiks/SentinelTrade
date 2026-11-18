"""Esquema relacional (SQL). Restrições CHECK/UNIQUE/FK garantem no banco as regras críticas:

* idempotência de ordens (UNIQUE chave_idempotencia — RN08/RF-20)
* idempotência do retorno da Bolsa (UNIQUE id_evento — CSU16)
* saldo e posições nunca negativos (RNF-17)
* auditoria append-only (triggers — RN12, ver banco.py)
"""
from __future__ import annotations

from sqlalchemy import (Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer,
                        MetaData, Numeric, String, Table, Text, UniqueConstraint)

metadata = MetaData()

DIN = Numeric(18, 2)
PRECO4 = Numeric(18, 4)

investidores = Table(
    "investidores", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("nome", String(120), nullable=False),
    Column("documento", String(20), nullable=False, unique=True),
    Column("ativo", Boolean, nullable=False, default=True),
)

usuarios = Table(
    "usuarios", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("login", String(60), nullable=False, unique=True),
    Column("senha_hash", String(255), nullable=False),
    Column("perfil", String(20), nullable=False),
    Column("ativo", Boolean, nullable=False, default=True),
    Column("tentativas_falhas", Integer, nullable=False, default=0),
    Column("bloqueado_ate", DateTime),
    Column("investidor_id", Integer, ForeignKey("investidores.id")),
    CheckConstraint("perfil IN ('INVESTIDOR','OPERADOR_RISCO','ADMINISTRADOR','AUDITOR')",
                    name="ck_usuarios_perfil"),
)

desafios_mfa = Table(
    "desafios_mfa", metadata,
    Column("id", String(36), primary_key=True),
    Column("usuario_id", Integer, ForeignKey("usuarios.id"), nullable=False),
    Column("codigo_hash", String(64), nullable=False),
    Column("expira_em", DateTime, nullable=False),
    Column("usado", Boolean, nullable=False, default=False),
    Column("criado_em", DateTime, nullable=False),
)

contas = Table(
    "contas", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("investidor_id", Integer, ForeignKey("investidores.id"), nullable=False, unique=True),
    Column("saldo", DIN, nullable=False, default=0),
    Column("reservado", DIN, nullable=False, default=0),
    CheckConstraint("saldo >= 0", name="ck_contas_saldo_nao_negativo"),
    CheckConstraint("reservado >= 0", name="ck_contas_reservado_nao_negativo"),
    CheckConstraint("reservado <= saldo", name="ck_contas_reservado_ate_saldo"),
)

ativos = Table(
    "ativos", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("codigo", String(12), nullable=False, unique=True),
    Column("nome", String(120), nullable=False),
    Column("tipo", String(10), nullable=False),
    Column("lote_padrao", Integer, nullable=False, default=100),
    Column("situacao", String(12), nullable=False, default="NEGOCIAVEL"),
    CheckConstraint("tipo IN ('ACAO','ETF','FII')", name="ck_ativos_tipo"),
    CheckConstraint("situacao IN ('NEGOCIAVEL','SUSPENSO')", name="ck_ativos_situacao"),
    CheckConstraint("lote_padrao > 0", name="ck_ativos_lote"),
)

posicoes = Table(
    "posicoes", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("conta_id", Integer, ForeignKey("contas.id"), nullable=False),
    Column("ativo_id", Integer, ForeignKey("ativos.id"), nullable=False),
    Column("quantidade", Integer, nullable=False, default=0),
    Column("reservada", Integer, nullable=False, default=0),
    Column("preco_medio", PRECO4, nullable=False, default=0),
    UniqueConstraint("conta_id", "ativo_id", name="uq_posicoes_conta_ativo"),
    CheckConstraint("quantidade >= 0", name="ck_posicoes_quantidade"),
    CheckConstraint("reservada >= 0 AND reservada <= quantidade", name="ck_posicoes_reservada"),
)

cotacoes = Table(
    "cotacoes", metadata,
    Column("ativo_id", Integer, ForeignKey("ativos.id"), primary_key=True),
    Column("preco", DIN, nullable=False),
    Column("volume", Integer, nullable=False, default=0),
    Column("variacao", DIN, nullable=False, default=0),
    Column("atualizada_em", DateTime, nullable=False),
    CheckConstraint("preco > 0", name="ck_cotacoes_preco"),
)

limites_risco = Table(
    "limites_risco", metadata,
    Column("investidor_id", Integer, ForeignKey("investidores.id"), primary_key=True),
    Column("max_por_ordem", DIN, nullable=False),
    Column("max_diario", DIN, nullable=False),
    CheckConstraint("max_por_ordem > 0 AND max_diario >= max_por_ordem", name="ck_limites"),
)

ordens = Table(
    "ordens", metadata,
    Column("id", String(36), primary_key=True),
    Column("chave_idempotencia", String(80), nullable=False, unique=True),
    Column("investidor_id", Integer, ForeignKey("investidores.id"), nullable=False),
    Column("conta_id", Integer, ForeignKey("contas.id"), nullable=False),
    Column("ativo_id", Integer, ForeignKey("ativos.id"), nullable=False),
    Column("lado", String(6), nullable=False),
    Column("modalidade", String(10), nullable=False),
    Column("quantidade", Integer, nullable=False),
    Column("quantidade_executada", Integer, nullable=False, default=0),
    Column("preco_limite", DIN),
    Column("preco_reserva", DIN, nullable=False, default=0),
    Column("valor_estimado", DIN, nullable=False, default=0),
    Column("valor_reservado", DIN, nullable=False, default=0),
    Column("quantidade_reservada", Integer, nullable=False, default=0),
    Column("preco_medio_execucao", PRECO4, nullable=False, default=0),
    Column("estado", String(24), nullable=False),
    Column("tentativas", Integer, nullable=False, default=0),
    Column("proxima_tentativa_em", DateTime),
    Column("cancelamento_pendente", Boolean, nullable=False, default=False),
    Column("motivo_rejeicao", String(300)),
    Column("id_bolsa", String(60)),
    Column("correlacao_id", String(36), nullable=False),
    Column("criado_em", DateTime, nullable=False),
    Column("atualizado_em", DateTime, nullable=False),
    Column("versao", Integer, nullable=False, default=1),
    CheckConstraint("lado IN ('COMPRA','VENDA')", name="ck_ordens_lado"),
    CheckConstraint("modalidade IN ('MERCADO','LIMITADA')", name="ck_ordens_modalidade"),
    CheckConstraint("quantidade > 0", name="ck_ordens_quantidade"),
    CheckConstraint("quantidade_executada >= 0 AND quantidade_executada <= quantidade",
                    name="ck_ordens_executada"),
    CheckConstraint(
        "estado IN ('CRIADA','VALIDADA','ENVIADA','PARCIALMENTE_EXECUTADA','EXECUTADA',"
        "'REJEITADA','CANCELADA','FALHA','INTERVENCAO_MANUAL')", name="ck_ordens_estado"),
)
Index("ix_ordens_investidor_criado", ordens.c.investidor_id, ordens.c.criado_em)
Index("ix_ordens_estado", ordens.c.estado)

ordens_historico = Table(
    "ordens_historico", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ordem_id", String(36), ForeignKey("ordens.id"), nullable=False, index=True),
    Column("evento", String(20), nullable=False),
    Column("estado_anterior", String(24)),
    Column("estado_novo", String(24), nullable=False),
    Column("motivo", String(300)),
    Column("criado_em", DateTime, nullable=False),
)

operacoes = Table(
    "operacoes", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ordem_id", String(36), ForeignKey("ordens.id"), nullable=False, index=True),
    Column("ativo_id", Integer, ForeignKey("ativos.id"), nullable=False),
    Column("quantidade", Integer, nullable=False),
    Column("preco", DIN, nullable=False),
    Column("id_evento_bolsa", String(60), nullable=False, unique=True),
    Column("executada_em", DateTime, nullable=False),
    CheckConstraint("quantidade > 0 AND preco > 0", name="ck_operacoes_valores"),
)

eventos_bolsa = Table(
    "eventos_bolsa", metadata,
    Column("id_evento", String(60), primary_key=True),
    Column("ordem_id", String(36)),
    Column("tipo", String(20), nullable=False),
    Column("processado_em", DateTime, nullable=False),
)

notificacoes = Table(
    "notificacoes", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("investidor_id", Integer, ForeignKey("investidores.id"), index=True),
    Column("destinatario_perfil", String(20)),
    Column("ordem_id", String(36)),
    Column("tipo", String(30), nullable=False),
    Column("mensagem", String(400), nullable=False),
    Column("entregue", Boolean, nullable=False, default=False),
    Column("criado_em", DateTime, nullable=False),
)

fila_mensagens = Table(
    "fila_mensagens", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("topico", String(30), nullable=False),
    Column("payload", Text, nullable=False),
    Column("status", String(12), nullable=False, default="PENDENTE"),
    Column("tentativas", Integer, nullable=False, default=0),
    Column("max_tentativas", Integer, nullable=False, default=5),
    Column("proxima_tentativa_em", DateTime, nullable=False),
    Column("ultimo_erro", String(300)),
    Column("criado_em", DateTime, nullable=False),
    Column("concluida_em", DateTime),
    CheckConstraint("status IN ('PENDENTE','CONCLUIDA','MORTA','CANCELADA')", name="ck_fila_status"),
)
Index("ix_fila_status_topico", fila_mensagens.c.status, fila_mensagens.c.topico)

auditoria = Table(
    "auditoria", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ocorrido_em", DateTime, nullable=False),
    Column("usuario", String(60), nullable=False),
    Column("perfil", String(20)),
    Column("acao", String(40), nullable=False),
    Column("entidade", String(30)),
    Column("entidade_id", String(60)),
    Column("resultado", String(12), nullable=False),
    Column("origem", String(40)),
    Column("correlacao_id", String(36)),
    Column("detalhes", Text),
    Column("hash_anterior", String(64), nullable=False),
    Column("hash", String(64), nullable=False, unique=True),
)
Index("ix_auditoria_ocorrido", auditoria.c.ocorrido_em)

suspensoes = Table(
    "suspensoes", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("escopo", String(20), nullable=False),  # 'MERCADO' ou código do ativo
    Column("motivo", String(300), nullable=False),
    Column("automatica", Boolean, nullable=False, default=False),
    Column("ativa", Boolean, nullable=False, default=True),
    Column("acionada_por", String(60), nullable=False),
    Column("criada_em", DateTime, nullable=False),
    Column("encerrada_em", DateTime),
    Column("encerrada_por", String(60)),
)
