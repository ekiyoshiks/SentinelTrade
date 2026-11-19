"""CSU12 — Definir Limites de Risco  e  CSU13 — Acionar Indisponibilidade Segura."""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Callable

from ..config import Configuracoes
from ..dominio.excecoes import AcessoNegadoError, ConflitoError, NaoEncontradoError, ValidacaoEntradaError
from ..dominio.estados import ESTADOS_ALTERAVEIS
from ..dominio.relogio import Relogio
from ..dominio.risco import LimiteRisco
from ..dominio.usuarios import Perfil, Usuario
from ..persistencia.banco import Banco
from ..persistencia.mapeamento import Suspensao
from ..persistencia.repositorios import (RepositorioCadastros, RepositorioMercado, RepositorioOrdens,
                                         RepositorioSuspensoes)
from .auditoria import AuditoriaService
from .notificacoes import NotificacaoService

log = logging.getLogger(__name__)
ESCOPO_MERCADO = "MERCADO"


class RiscoService:
    def __init__(self, banco: Banco, relogio: Relogio, config: Configuracoes, auditoria: AuditoriaService,
                 notificacoes: NotificacaoService, verificadores_saude: list[Callable[[], bool]]):
        self._banco, self._relogio, self._config = banco, relogio, config
        self._auditoria, self._notificacoes = auditoria, notificacoes
        self._saude = verificadores_saude

    @staticmethod
    def _exigir(usuario: Usuario, permissao: str) -> None:
        if not usuario.pode(permissao):
            raise AcessoNegadoError("Seu perfil não tem permissão para esta operação.")

    # ------------------------------------------------------------------ limites
    def definir_limites(self, operador: Usuario, investidor_id: int, max_por_ordem: Decimal,
                        max_diario: Decimal, origem: str = "API") -> dict:
        self._exigir(operador, "limite:definir")
        with self._banco.exclusivo():
            with self._banco.transacao() as s:
                cadastros = RepositorioCadastros(s)
                if cadastros.investidor(investidor_id) is None:
                    raise NaoEncontradoError("Investidor não encontrado.")
                limite = cadastros.limite(investidor_id)
                if limite is None:
                    limite = LimiteRisco(investidor_id, Decimal("1"), Decimal("1"))
                    s.add(limite)
                anterior = (str(limite.max_por_ordem), str(limite.max_diario))
                limite.definir(max_por_ordem, max_diario, self._config.teto_corretora_ordem,
                               self._config.teto_corretora_dia)
                self._auditoria.registrar(
                    s, usuario=operador.login, perfil=operador.perfil.value, acao="LIMITE_DEFINIDO",
                    entidade="investidor", entidade_id=str(investidor_id), origem=origem,
                    detalhes={"antes": anterior, "depois": (str(limite.max_por_ordem), str(limite.max_diario))})
                return {"investidor_id": investidor_id, "max_por_ordem": str(limite.max_por_ordem),
                        "max_diario": str(limite.max_diario)}

    def listar_limites(self, usuario: Usuario) -> list[dict]:
        self._exigir(usuario, "limite:definir")
        with self._banco.transacao() as s:
            cadastros = RepositorioCadastros(s)
            limites = {l.investidor_id: l for l in cadastros.limites()}
            return [{"investidor_id": i.id, "nome": i.nome,
                     "max_por_ordem": str(limites[i.id].max_por_ordem) if i.id in limites else None,
                     "max_diario": str(limites[i.id].max_diario) if i.id in limites else None}
                    for i in cadastros.investidores()]

    # ------------------------------------------------------------------ suspensão
    def acionar_suspensao(self, operador: Usuario, escopo: str, motivo: str, origem: str = "API") -> dict:
        """Passos 1-5 do CSU13. ``escopo`` é 'MERCADO' ou o código de um ativo."""
        self._exigir(operador, "suspensao:acionar")
        motivo = (motivo or "").strip()
        if not motivo:
            raise ValidacaoEntradaError("Informe o motivo da suspensão.")
        escopo = escopo.strip().upper() or ESCOPO_MERCADO
        with self._banco.exclusivo():
            with self._banco.transacao() as s:
                if escopo != ESCOPO_MERCADO and RepositorioMercado(s).ativo_por_codigo(escopo) is None:
                    raise NaoEncontradoError("Ativo não encontrado para o escopo informado.")
                if any(x.escopo == escopo for x in RepositorioSuspensoes(s).ativas()):
                    raise ConflitoError("Já existe suspensão ativa para este escopo.")
                suspensao = Suspensao(escopo=escopo, motivo=motivo[:300], automatica=False, ativa=True,
                                      acionada_por=operador.login, criada_em=self._relogio.agora())
                s.add(suspensao)
                em_andamento = sum(1 for o in RepositorioOrdens(s).listar(limite=1000)
                                   if o.estado in ESTADOS_ALTERAVEIS)
                self._auditoria.registrar(
                    s, usuario=operador.login, perfil=operador.perfil.value, acao="SUSPENSAO_ACIONADA",
                    entidade="suspensao", entidade_id=escopo, origem=origem,
                    detalhes={"motivo": motivo, "ordens_em_andamento": em_andamento})
                s.flush()
                return {"id": suspensao.id, "escopo": escopo, "motivo": motivo,
                        "ordens_em_andamento": em_andamento}

    def encerrar_suspensao(self, operador: Usuario, escopo: str, origem: str = "API") -> dict:
        """Fluxo alternativo do CSU13: só reabre se os componentes estiverem saudáveis."""
        self._exigir(operador, "suspensao:acionar")
        escopo = escopo.strip().upper() or ESCOPO_MERCADO
        with self._banco.exclusivo():
            with self._banco.transacao() as s:
                alvo = next((x for x in RepositorioSuspensoes(s).ativas() if x.escopo == escopo), None)
                if alvo is None:
                    raise NaoEncontradoError("Não há suspensão ativa para este escopo.")
                if not all(verificar() for verificar in self._saude):
                    raise ConflitoError("Componentes ainda indisponíveis: a suspensão não pode ser encerrada.")
                alvo.ativa = False
                alvo.encerrada_em = self._relogio.agora()
                alvo.encerrada_por = operador.login
                self._auditoria.registrar(s, usuario=operador.login, perfil=operador.perfil.value,
                                          acao="SUSPENSAO_ENCERRADA", entidade="suspensao",
                                          entidade_id=escopo, origem=origem)
                return {"escopo": escopo, "encerrada": True}

    def suspensao_ativa(self, s, codigo_ativo: str) -> Suspensao | None:
        """Suspensão que atinge o ativo (global ou específica), se houver."""
        for suspensao in RepositorioSuspensoes(s).ativas():
            if suspensao.escopo in (ESCOPO_MERCADO, codigo_ativo.upper()):
                return suspensao
        return None

    def ativar_automaticamente(self, motivo: str) -> None:
        """Falha grave: o próprio sistema bloqueia novas ordens, notifica o Operador e registra."""
        try:
            with self._banco.exclusivo():
                with self._banco.transacao() as s:
                    if any(x.escopo == ESCOPO_MERCADO for x in RepositorioSuspensoes(s).ativas()):
                        return
                    s.add(Suspensao(escopo=ESCOPO_MERCADO, motivo=motivo[:300], automatica=True, ativa=True,
                                    acionada_por="SISTEMA", criada_em=self._relogio.agora()))
                    self._auditoria.registrar(s, usuario="SISTEMA", acao="SUSPENSAO_AUTOMATICA",
                                              entidade="suspensao", entidade_id=ESCOPO_MERCADO,
                                              resultado="ALERTA", detalhes={"motivo": motivo})
                    self._notificacoes.criar(s, tipo="SUSPENSAO_AUTOMATICA", perfil=Perfil.OPERADOR_RISCO.value,
                                             mensagem=f"Indisponibilidade segura ativada automaticamente: {motivo}")
        except Exception:  # pragma: no cover - último recurso
            log.exception("Não foi possível registrar a suspensão automática")

    def mercado_suspenso(self) -> bool:
        """Informação pública e não sensível: há suspensão global de novas ordens?"""
        with self._banco.transacao() as s:
            return any(x.escopo == ESCOPO_MERCADO for x in RepositorioSuspensoes(s).ativas())

    def listar_suspensoes(self, usuario: Usuario) -> list[dict]:
        self._exigir(usuario, "painel:ver")
        with self._banco.transacao() as s:
            return [{"id": x.id, "escopo": x.escopo, "motivo": x.motivo, "automatica": x.automatica,
                     "ativa": x.ativa, "acionada_por": x.acionada_por,
                     "criada_em": x.criada_em.isoformat(), "encerrada_em":
                     x.encerrada_em.isoformat() if x.encerrada_em else None}
                    for x in RepositorioSuspensoes(s).todas()]
