"""Calendário do pregão simulado (RN04)."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from ..config import Configuracoes

try:
    FUSO = ZoneInfo("America/Sao_Paulo")
except Exception:  # pragma: no cover - ambiente sem tzdata
    FUSO = timezone(timedelta(hours=-3))


def _hora(texto: str) -> time:
    h, m = texto.split(":")
    return time(int(h), int(m))


def inicio_do_dia_utc(agora_utc: datetime) -> datetime:
    """Meia-noite do dia local (fuso do pregão) convertida para UTC ingênuo."""
    local = agora_utc.replace(tzinfo=timezone.utc).astimezone(FUSO)
    meia_noite = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return meia_noite.astimezone(timezone.utc).replace(tzinfo=None)


class CalendarioPregao:
    def __init__(self, config: Configuracoes):
        self._sempre_aberto = config.mercado_sempre_aberto
        self._inicio = _hora(config.pregao_inicio)
        self._fim = _hora(config.pregao_fim)

    def _local(self, agora_utc: datetime) -> datetime:
        return agora_utc.replace(tzinfo=timezone.utc).astimezone(FUSO)

    def esta_aberto(self, agora_utc: datetime) -> bool:
        if self._sempre_aberto:
            return True
        local = self._local(agora_utc)
        return local.weekday() < 5 and self._inicio <= local.time() < self._fim

    def proximo_horario(self, agora_utc: datetime) -> str:
        local = self._local(agora_utc)
        dia = local
        if local.weekday() < 5 and local.time() < self._inicio:
            alvo = dia
        else:
            alvo = dia + timedelta(days=1)
        while alvo.weekday() >= 5:
            alvo += timedelta(days=1)
        return f"{alvo.strftime('%d/%m/%Y')} às {self._inicio.strftime('%H:%M')}"
