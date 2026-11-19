"""Fila de mensagens durável (RNF-14), armazenada no banco, com fila de mensagens mortas.

* Mensagem gravada na mesma transação do caso de uso → nunca se perde (padrão "outbox").
* Falhas são reenviadas com espera crescente; ao esgotar as tentativas a mensagem vai para MORTA.
"""
from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Configuracoes
from ..dominio.relogio import Relogio
from ..persistencia.mapeamento import MensagemFila

BOLSA_ENVIO = "BOLSA_ENVIO"
NOTIFICACAO = "NOTIFICACAO"


class FilaMensagens:
    def __init__(self, relogio: Relogio, config: Configuracoes):
        self._relogio = relogio
        self._config = config

    def publicar(self, s: Session, topico: str, payload: dict) -> MensagemFila:
        agora = self._relogio.agora()
        msg = MensagemFila(topico=topico, payload=json.dumps(payload), status="PENDENTE", tentativas=0,
                           max_tentativas=self._config.fila_max_tentativas, proxima_tentativa_em=agora,
                           criado_em=agora)
        s.add(msg)
        s.flush()
        return msg

    def proximas(self, s: Session, topico: str, limite: int = 50) -> list[MensagemFila]:
        agora = self._relogio.agora()
        return list(s.scalars(select(MensagemFila).where(
            MensagemFila.topico == topico, MensagemFila.status == "PENDENTE",
            MensagemFila.proxima_tentativa_em <= agora).order_by(MensagemFila.id).limit(limite)))

    @staticmethod
    def dados(msg: MensagemFila) -> dict:
        return json.loads(msg.payload)

    def concluir(self, msg: MensagemFila) -> None:
        msg.status = "CONCLUIDA"
        msg.concluida_em = self._relogio.agora()

    def falhar(self, msg: MensagemFila, erro: str) -> None:
        """Nova tentativa com espera crescente; esgotadas, vai para a fila de mensagens mortas."""
        msg.tentativas += 1
        msg.ultimo_erro = erro[:300]
        if msg.tentativas >= msg.max_tentativas:
            msg.status = "MORTA"
        else:
            espera = self._config.reprocessamento_espera_base_s * (2 ** (msg.tentativas - 1))
            msg.proxima_tentativa_em = self._relogio.agora() + timedelta(seconds=espera)

    def cancelar_por_ordem(self, s: Session, topico: str, ordem_id: str) -> int:
        cancelados = 0
        for msg in s.scalars(select(MensagemFila).where(
                MensagemFila.topico == topico, MensagemFila.status == "PENDENTE")):
            if self.dados(msg).get("ordem_id") == ordem_id:
                msg.status = "CANCELADA"
                msg.concluida_em = self._relogio.agora()
                cancelados += 1
        return cancelados
