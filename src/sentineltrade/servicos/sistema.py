"""Composição do sistema (injeção de dependências) e ciclo de processamento em segundo plano."""
from __future__ import annotations

import logging
import threading
from decimal import Decimal

from ..config import Configuracoes
from ..dominio.relogio import Relogio, RelogioSistema
from ..integracoes.interfaces import BolsaGateway, Notificador, ProvedorCotacoes
from ..integracoes.simuladores import BolsaSimulada, NotificadorSimulado, ProvedorCotacoesSimulado
from ..persistencia.banco import Banco
from ..regras.calendario import CalendarioPregao
from ..regras.ordem import ValidadorOrdem
from ..regras.senha import HashArgon2
from ..dominio.usuarios import HashSenha
from .auditoria import AuditoriaService
from .autenticacao import AutenticacaoService
from .cadastros import CadastroService
from .consultas import ConsultaService
from .cotacoes import CotacaoService
from .fila import FilaMensagens
from .notificacoes import NotificacaoService
from .ordens import OrdemService
from .retorno_bolsa import RetornoBolsaService
from .risco import RiscoService
from .transmissao import TransmissaoBolsaService

log = logging.getLogger(__name__)

PRECOS_INICIAIS = {
    "PETR4": Decimal("38.50"), "VALE3": Decimal("62.10"), "ITUB4": Decimal("33.20"),
    "BBAS3": Decimal("27.80"), "MGLU3": Decimal("9.75"), "BOVA11": Decimal("128.40"),
    "HGLG11": Decimal("158.30"), "XPLG11": Decimal("102.90"),
}


class Sistema:
    """Agrupa banco, integrações e serviços. Um único objeto por processo."""

    def __init__(self, config: Configuracoes | None = None, *, banco: Banco | None = None,
                 relogio: Relogio | None = None, provedor: ProvedorCotacoes | None = None,
                 bolsa: BolsaGateway | None = None, notificador: Notificador | None = None,
                 hasher: HashSenha | None = None, validador: ValidadorOrdem | None = None):
        self.config = config or Configuracoes.de_ambiente()
        self.relogio = relogio or RelogioSistema()
        self.banco = banco or Banco(self.config.database_url)
        self.provedor = provedor or ProvedorCotacoesSimulado(self.relogio, PRECOS_INICIAIS,
                                                             self.config.simulador_seed)
        self.bolsa = bolsa or BolsaSimulada(self.relogio, self.provedor, self.config.simulador_seed)
        self.notificador = notificador or NotificadorSimulado()
        self.hasher = hasher or HashArgon2()
        self.validador = validador or ValidadorOrdem.padrao()
        self.calendario = CalendarioPregao(self.config)

        self.auditoria = AuditoriaService(self.relogio)
        self.fila = FilaMensagens(self.relogio, self.config)
        self.notificacoes = NotificacaoService(self.banco, self.relogio, self.fila, self.notificador)
        self.autenticacao = AutenticacaoService(self.banco, self.relogio, self.config, self.hasher,
                                                self.notificador, self.auditoria)
        self.cotacoes = CotacaoService(self.banco, self.relogio, self.config, self.provedor, self.auditoria)
        self.risco = RiscoService(self.banco, self.relogio, self.config, self.auditoria, self.notificacoes,
                                  [self.banco.saudavel, self.bolsa.saude])
        self.retorno = RetornoBolsaService(self.banco, self.relogio, self.bolsa, self.auditoria,
                                           self.notificacoes)
        self.transmissao = TransmissaoBolsaService(self.banco, self.relogio, self.config, self.bolsa,
                                                   self.fila, self.auditoria, self.notificacoes)
        self.ordens = OrdemService(self.banco, self.relogio, self.config, self.auditoria, self.fila,
                                   self.notificacoes, self.risco, self.retorno, self.bolsa, self.validador,
                                   self.calendario)
        registrar = (self.provedor.registrar_ativo if isinstance(self.provedor, ProvedorCotacoesSimulado)
                     else None)
        self.cadastros = CadastroService(self.banco, self.relogio, self.config, self.auditoria,
                                         self.autenticacao, registrar)
        self.consultas = ConsultaService(self.banco, self.relogio, self.auditoria, self.notificacoes,
                                         self.status_integracoes)

    # ------------------------------------------------------------------
    def provedor_preco(self, codigo: str) -> Decimal:
        """Preço de referência de um ativo (usado só para montar dados de exemplo)."""
        ultimo = getattr(self.provedor, "ultimo_preco", lambda _c: None)(codigo)
        return ultimo or PRECOS_INICIAIS.get(codigo, Decimal("10.00"))

    def status_integracoes(self) -> dict:
        bolsa, provedor, notificador = self.bolsa, self.provedor, self.notificador
        return {
            "banco_ok": self.banco.saudavel(),
            "bolsa_ok": bolsa.saude(),
            "bolsa_modo": getattr(bolsa, "modo", "N/D"),
            "bolsa_execucao_parcial": getattr(bolsa, "execucao_parcial", False),
            "provedor_ok": self.cotacoes.provedor_ok,
            "provedor_pausado": getattr(provedor, "pausado", False),
            "notificador_falhando": getattr(notificador, "falhar", False),
        }

    def tick(self) -> dict:
        """Um ciclo de processamento: cotações → envio à Bolsa → retornos → reprocesso → notificações."""
        return {
            "cotacoes": self.cotacoes.atualizar(),
            "enviadas": self.transmissao.processar_envios(),
            "retornos": self.retorno.sincronizar(),
            "reprocessamento": self.transmissao.reprocessar_pendentes(),
            "notificacoes_entregues": self.notificacoes.entregar_pendentes(),
        }

    def iniciar_worker(self) -> "WorkerSegundoPlano":
        worker = WorkerSegundoPlano(self)
        worker.start()
        return worker


class WorkerSegundoPlano(threading.Thread):
    """Executa ``Sistema.tick`` periodicamente (fila, retornos, reprocessamento)."""

    def __init__(self, sistema: Sistema):
        super().__init__(name="sentinel-worker", daemon=True)
        self._sistema = sistema
        self._parar = threading.Event()

    def run(self) -> None:
        while not self._parar.wait(self._sistema.config.intervalo_worker_s):
            try:
                self._sistema.tick()
            except Exception:  # o ciclo nunca deve morrer
                log.exception("Erro no ciclo de processamento")

    def parar(self) -> None:
        self._parar.set()
