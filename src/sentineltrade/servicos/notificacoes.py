"""CSU17 — Notificar Investidor (e Operador de Risco).

A notificação fica sempre visível na plataforma; a entrega pelo Serviço de Notificação é
assíncrona (fila), com nova tentativa controlada em caso de falha (RNF-14).
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ..dominio.excecoes import IntegracaoError
from ..dominio.relogio import Relogio
from ..integracoes.interfaces import Notificador
from ..persistencia.banco import Banco
from ..persistencia.mapeamento import Notificacao
from .fila import NOTIFICACAO, FilaMensagens

log = logging.getLogger(__name__)


class NotificacaoService:
    def __init__(self, banco: Banco, relogio: Relogio, fila: FilaMensagens, notificador: Notificador):
        self._banco, self._relogio, self._fila, self._notificador = banco, relogio, fila, notificador

    def criar(self, s: Session, *, tipo: str, mensagem: str, investidor_id: int | None = None,
              perfil: str | None = None, ordem_id: str | None = None) -> Notificacao:
        notificacao = Notificacao(investidor_id=investidor_id, destinatario_perfil=perfil, ordem_id=ordem_id,
                                  tipo=tipo, mensagem=mensagem[:400], entregue=False,
                                  criado_em=self._relogio.agora())
        s.add(notificacao)
        s.flush()
        self._fila.publicar(s, NOTIFICACAO, {"notificacao_id": notificacao.id})
        return notificacao

    def entregar_pendentes(self, limite: int = 50) -> int:
        """Entrega as notificações da fila. Falhas ficam para nova tentativa."""
        entregues = 0
        with self._banco.exclusivo():
            with self._banco.transacao() as s:
                ids = [(m.id, self._fila.dados(m)["notificacao_id"])
                       for m in self._fila.proximas(s, NOTIFICACAO, limite)]
            for msg_id, notificacao_id in ids:
                with self._banco.transacao() as s:
                    from ..persistencia.mapeamento import MensagemFila
                    msg = s.get(MensagemFila, msg_id)
                    notificacao = s.get(Notificacao, notificacao_id)
                    if notificacao is None:
                        self._fila.concluir(msg)
                        continue
                    destino = (f"investidor:{notificacao.investidor_id}" if notificacao.investidor_id
                               else f"perfil:{notificacao.destinatario_perfil}")
                    try:
                        self._notificador.entregar(destino, notificacao.mensagem)
                        notificacao.entregue = True
                        self._fila.concluir(msg)
                        entregues += 1
                    except IntegracaoError as erro:
                        log.warning("Falha ao entregar notificação %s: %s", notificacao_id, erro)
                        self._fila.falhar(msg, str(erro))
        return entregues
