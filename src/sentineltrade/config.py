"""Configurações do sistema, lidas de variáveis de ambiente (.env).

Nenhum segredo é versionado: os valores padrão são apenas para desenvolvimento.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path


def _carregar_dotenv(caminho: Path) -> None:
    """Carrega um arquivo .env simples (CHAVE=valor) sem sobrescrever o ambiente."""
    if not caminho.is_file():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip())


def _bool(valor: str | None, padrao: bool) -> bool:
    if valor is None:
        return padrao
    return valor.strip().lower() in {"1", "true", "sim", "yes", "on"}


@dataclass(frozen=True)
class Configuracoes:
    # Banco (RF/RNF: banco relacional SQL). SQLite por padrão; PostgreSQL via DATABASE_URL.
    database_url: str = "sqlite:///data/local/sentineltrade.db"

    # Segurança (RN10, RN11, RNF-02)
    jwt_secret: str = "troque-esta-chave-em-desenvolvimento"
    mfa_max_tentativas: int = 5
    bloqueio_minutos: int = 15
    mfa_validade_segundos: int = 60
    sessao_validade_segundos: int = 3600

    # Integrações (RNF-11, RNF-12)
    bolsa_timeout_ms: int = 2000
    bolsa_max_tentativas: int = 3
    reprocessamento_espera_base_s: int = 5
    fila_max_tentativas: int = 5

    # Regras de negócio (RN03..RN07)
    cotacao_max_idade_s: int = 5
    faixa_preco_limitada: Decimal = Decimal("0.10")
    margem_reserva_mercado: Decimal = Decimal("0.05")
    teto_corretora_ordem: Decimal = Decimal("1000000.00")
    teto_corretora_dia: Decimal = Decimal("5000000.00")
    mercado_sempre_aberto: bool = True
    pregao_inicio: str = "10:00"
    pregao_fim: str = "17:00"

    # Simulação / execução
    modo_simulacao: bool = True
    intervalo_worker_s: float = 1.0
    simulador_seed: int = 42

    @classmethod
    def de_ambiente(cls) -> "Configuracoes":
        _carregar_dotenv(Path(".env"))
        e = os.environ
        return cls(
            database_url=e.get("DATABASE_URL", cls.database_url),
            jwt_secret=e.get("JWT_SECRET") or secrets.token_urlsafe(32),   # sem JWT_SECRET: chave aleatória por execução
            mfa_max_tentativas=int(e.get("MFA_MAX_TENTATIVAS", cls.mfa_max_tentativas)),
            bloqueio_minutos=int(e.get("BLOQUEIO_MINUTOS", cls.bloqueio_minutos)),
            mfa_validade_segundos=int(e.get("MFA_VALIDADE_SEGUNDOS", cls.mfa_validade_segundos)),
            bolsa_timeout_ms=int(e.get("BOLSA_TIMEOUT_MS", cls.bolsa_timeout_ms)),
            bolsa_max_tentativas=int(e.get("BOLSA_MAX_TENTATIVAS", cls.bolsa_max_tentativas)),
            reprocessamento_espera_base_s=int(
                e.get("REPROCESSAMENTO_ESPERA_BASE_S", cls.reprocessamento_espera_base_s)
            ),
            cotacao_max_idade_s=int(e.get("COTACAO_MAX_IDADE_S", cls.cotacao_max_idade_s)),
            mercado_sempre_aberto=_bool(e.get("MERCADO_SEMPRE_ABERTO"), cls.mercado_sempre_aberto),
            modo_simulacao=_bool(e.get("MODO_SIMULACAO"), cls.modo_simulacao),
            intervalo_worker_s=float(e.get("INTERVALO_WORKER_S", cls.intervalo_worker_s)),
            simulador_seed=int(e.get("SIMULADOR_SEED", cls.simulador_seed)),
        )
