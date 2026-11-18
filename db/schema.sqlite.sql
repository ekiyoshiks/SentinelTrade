CREATE TABLE ativos (
	id INTEGER NOT NULL, 
	codigo VARCHAR(12) NOT NULL, 
	nome VARCHAR(120) NOT NULL, 
	tipo VARCHAR(10) NOT NULL, 
	lote_padrao INTEGER NOT NULL, 
	situacao VARCHAR(12) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_ativos_tipo CHECK (tipo IN ('ACAO','ETF','FII')), 
	CONSTRAINT ck_ativos_situacao CHECK (situacao IN ('NEGOCIAVEL','SUSPENSO')), 
	CONSTRAINT ck_ativos_lote CHECK (lote_padrao > 0), 
	UNIQUE (codigo)
);

CREATE TABLE auditoria (
	id INTEGER NOT NULL, 
	ocorrido_em DATETIME NOT NULL, 
	usuario VARCHAR(60) NOT NULL, 
	perfil VARCHAR(20), 
	acao VARCHAR(40) NOT NULL, 
	entidade VARCHAR(30), 
	entidade_id VARCHAR(60), 
	resultado VARCHAR(12) NOT NULL, 
	origem VARCHAR(40), 
	correlacao_id VARCHAR(36), 
	detalhes TEXT, 
	hash_anterior VARCHAR(64) NOT NULL, 
	hash VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (hash)
);

CREATE INDEX ix_auditoria_ocorrido ON auditoria (ocorrido_em);

CREATE TABLE eventos_bolsa (
	id_evento VARCHAR(60) NOT NULL, 
	ordem_id VARCHAR(36), 
	tipo VARCHAR(20) NOT NULL, 
	processado_em DATETIME NOT NULL, 
	PRIMARY KEY (id_evento)
);

CREATE TABLE fila_mensagens (
	id INTEGER NOT NULL, 
	topico VARCHAR(30) NOT NULL, 
	payload TEXT NOT NULL, 
	status VARCHAR(12) NOT NULL, 
	tentativas INTEGER NOT NULL, 
	max_tentativas INTEGER NOT NULL, 
	proxima_tentativa_em DATETIME NOT NULL, 
	ultimo_erro VARCHAR(300), 
	criado_em DATETIME NOT NULL, 
	concluida_em DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_fila_status CHECK (status IN ('PENDENTE','CONCLUIDA','MORTA','CANCELADA'))
);

CREATE INDEX ix_fila_status_topico ON fila_mensagens (status, topico);

CREATE TABLE investidores (
	id INTEGER NOT NULL, 
	nome VARCHAR(120) NOT NULL, 
	documento VARCHAR(20) NOT NULL, 
	ativo BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (documento)
);

CREATE TABLE suspensoes (
	id INTEGER NOT NULL, 
	escopo VARCHAR(20) NOT NULL, 
	motivo VARCHAR(300) NOT NULL, 
	automatica BOOLEAN NOT NULL, 
	ativa BOOLEAN NOT NULL, 
	acionada_por VARCHAR(60) NOT NULL, 
	criada_em DATETIME NOT NULL, 
	encerrada_em DATETIME, 
	encerrada_por VARCHAR(60), 
	PRIMARY KEY (id)
);

CREATE TABLE contas (
	id INTEGER NOT NULL, 
	investidor_id INTEGER NOT NULL, 
	saldo NUMERIC(18, 2) NOT NULL, 
	reservado NUMERIC(18, 2) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_contas_saldo_nao_negativo CHECK (saldo >= 0), 
	CONSTRAINT ck_contas_reservado_nao_negativo CHECK (reservado >= 0), 
	CONSTRAINT ck_contas_reservado_ate_saldo CHECK (reservado <= saldo), 
	UNIQUE (investidor_id), 
	FOREIGN KEY(investidor_id) REFERENCES investidores (id)
);

CREATE TABLE cotacoes (
	ativo_id INTEGER NOT NULL, 
	preco NUMERIC(18, 2) NOT NULL, 
	volume INTEGER NOT NULL, 
	variacao NUMERIC(18, 2) NOT NULL, 
	atualizada_em DATETIME NOT NULL, 
	PRIMARY KEY (ativo_id), 
	CONSTRAINT ck_cotacoes_preco CHECK (preco > 0), 
	FOREIGN KEY(ativo_id) REFERENCES ativos (id)
);

CREATE TABLE limites_risco (
	investidor_id INTEGER NOT NULL, 
	max_por_ordem NUMERIC(18, 2) NOT NULL, 
	max_diario NUMERIC(18, 2) NOT NULL, 
	PRIMARY KEY (investidor_id), 
	CONSTRAINT ck_limites CHECK (max_por_ordem > 0 AND max_diario >= max_por_ordem), 
	FOREIGN KEY(investidor_id) REFERENCES investidores (id)
);

CREATE TABLE notificacoes (
	id INTEGER NOT NULL, 
	investidor_id INTEGER, 
	destinatario_perfil VARCHAR(20), 
	ordem_id VARCHAR(36), 
	tipo VARCHAR(30) NOT NULL, 
	mensagem VARCHAR(400) NOT NULL, 
	entregue BOOLEAN NOT NULL, 
	criado_em DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(investidor_id) REFERENCES investidores (id)
);

CREATE INDEX ix_notificacoes_investidor_id ON notificacoes (investidor_id);

CREATE TABLE usuarios (
	id INTEGER NOT NULL, 
	login VARCHAR(60) NOT NULL, 
	senha_hash VARCHAR(255) NOT NULL, 
	perfil VARCHAR(20) NOT NULL, 
	ativo BOOLEAN NOT NULL, 
	tentativas_falhas INTEGER NOT NULL, 
	bloqueado_ate DATETIME, 
	investidor_id INTEGER, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_usuarios_perfil CHECK (perfil IN ('INVESTIDOR','OPERADOR_RISCO','ADMINISTRADOR','AUDITOR')), 
	UNIQUE (login), 
	FOREIGN KEY(investidor_id) REFERENCES investidores (id)
);

CREATE TABLE desafios_mfa (
	id VARCHAR(36) NOT NULL, 
	usuario_id INTEGER NOT NULL, 
	codigo_hash VARCHAR(64) NOT NULL, 
	expira_em DATETIME NOT NULL, 
	usado BOOLEAN NOT NULL, 
	criado_em DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(usuario_id) REFERENCES usuarios (id)
);

CREATE TABLE ordens (
	id VARCHAR(36) NOT NULL, 
	chave_idempotencia VARCHAR(80) NOT NULL, 
	investidor_id INTEGER NOT NULL, 
	conta_id INTEGER NOT NULL, 
	ativo_id INTEGER NOT NULL, 
	lado VARCHAR(6) NOT NULL, 
	modalidade VARCHAR(10) NOT NULL, 
	quantidade INTEGER NOT NULL, 
	quantidade_executada INTEGER NOT NULL, 
	preco_limite NUMERIC(18, 2), 
	preco_reserva NUMERIC(18, 2) NOT NULL, 
	valor_estimado NUMERIC(18, 2) NOT NULL, 
	valor_reservado NUMERIC(18, 2) NOT NULL, 
	quantidade_reservada INTEGER NOT NULL, 
	preco_medio_execucao NUMERIC(18, 4) NOT NULL, 
	estado VARCHAR(24) NOT NULL, 
	tentativas INTEGER NOT NULL, 
	proxima_tentativa_em DATETIME, 
	cancelamento_pendente BOOLEAN NOT NULL, 
	motivo_rejeicao VARCHAR(300), 
	id_bolsa VARCHAR(60), 
	correlacao_id VARCHAR(36) NOT NULL, 
	criado_em DATETIME NOT NULL, 
	atualizado_em DATETIME NOT NULL, 
	versao INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_ordens_lado CHECK (lado IN ('COMPRA','VENDA')), 
	CONSTRAINT ck_ordens_modalidade CHECK (modalidade IN ('MERCADO','LIMITADA')), 
	CONSTRAINT ck_ordens_quantidade CHECK (quantidade > 0), 
	CONSTRAINT ck_ordens_executada CHECK (quantidade_executada >= 0 AND quantidade_executada <= quantidade), 
	CONSTRAINT ck_ordens_estado CHECK (estado IN ('CRIADA','VALIDADA','ENVIADA','PARCIALMENTE_EXECUTADA','EXECUTADA','REJEITADA','CANCELADA','FALHA','INTERVENCAO_MANUAL')), 
	UNIQUE (chave_idempotencia), 
	FOREIGN KEY(investidor_id) REFERENCES investidores (id), 
	FOREIGN KEY(conta_id) REFERENCES contas (id), 
	FOREIGN KEY(ativo_id) REFERENCES ativos (id)
);

CREATE INDEX ix_ordens_estado ON ordens (estado);

CREATE INDEX ix_ordens_investidor_criado ON ordens (investidor_id, criado_em);

CREATE TABLE posicoes (
	id INTEGER NOT NULL, 
	conta_id INTEGER NOT NULL, 
	ativo_id INTEGER NOT NULL, 
	quantidade INTEGER NOT NULL, 
	reservada INTEGER NOT NULL, 
	preco_medio NUMERIC(18, 4) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_posicoes_conta_ativo UNIQUE (conta_id, ativo_id), 
	CONSTRAINT ck_posicoes_quantidade CHECK (quantidade >= 0), 
	CONSTRAINT ck_posicoes_reservada CHECK (reservada >= 0 AND reservada <= quantidade), 
	FOREIGN KEY(conta_id) REFERENCES contas (id), 
	FOREIGN KEY(ativo_id) REFERENCES ativos (id)
);

CREATE TABLE operacoes (
	id INTEGER NOT NULL, 
	ordem_id VARCHAR(36) NOT NULL, 
	ativo_id INTEGER NOT NULL, 
	quantidade INTEGER NOT NULL, 
	preco NUMERIC(18, 2) NOT NULL, 
	id_evento_bolsa VARCHAR(60) NOT NULL, 
	executada_em DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_operacoes_valores CHECK (quantidade > 0 AND preco > 0), 
	FOREIGN KEY(ordem_id) REFERENCES ordens (id), 
	FOREIGN KEY(ativo_id) REFERENCES ativos (id), 
	UNIQUE (id_evento_bolsa)
);

CREATE INDEX ix_operacoes_ordem_id ON operacoes (ordem_id);

CREATE TABLE ordens_historico (
	id INTEGER NOT NULL, 
	ordem_id VARCHAR(36) NOT NULL, 
	evento VARCHAR(20) NOT NULL, 
	estado_anterior VARCHAR(24), 
	estado_novo VARCHAR(24) NOT NULL, 
	motivo VARCHAR(300), 
	criado_em DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ordem_id) REFERENCES ordens (id)
);

CREATE INDEX ix_ordens_historico_ordem_id ON ordens_historico (ordem_id);

CREATE TRIGGER IF NOT EXISTS auditoria_sem_update BEFORE UPDATE ON auditoria BEGIN SELECT RAISE(ABORT, 'RN12: auditoria e append-only'); END;

CREATE TRIGGER IF NOT EXISTS auditoria_sem_delete BEFORE DELETE ON auditoria BEGIN SELECT RAISE(ABORT, 'RN12: auditoria e append-only'); END;
