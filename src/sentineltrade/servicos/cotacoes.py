"""CSU15 — Atualizar Cotações  e  CSU02 — Consultar Cotações."""
from __future__ import annotations

import logging
from datetime import timedelta

from ..config import Configuracoes
from ..dominio.excecoes import IntegracaoError
from ..dominio.mercado import Cotacao
from ..dominio.relogio import Relogio
from ..integracoes.interfaces import ProvedorCotacoes
from ..persistencia.banco import Banco
from ..persistencia.repositorios import RepositorioMercado
from .auditoria import AuditoriaService

log = logging.getLogger(__name__)


class CotacaoService:
    def __init__(self, banco: Banco, relogio: Relogio, config: Configuracoes, provedor: ProvedorCotacoes,
                 auditoria: AuditoriaService):
        self._banco, self._relogio, self._config = banco, relogio, config
        self._provedor, self._auditoria = provedor, auditoria
        self.provedor_ok = True

    def atualizar(self) -> dict:
        """Recebe cotações do provedor, descarta as inválidas/fora de ordem e grava as demais."""
        resultado = {"atualizadas": 0, "descartadas": 0, "provedor_ok": True}
        try:
            recebidas = self._provedor.obter()
        except IntegracaoError:
            self.provedor_ok = False
            resultado["provedor_ok"] = False
            return resultado  # dados ficam defasados; as regras (RN07) e a consulta sinalizam
        self.provedor_ok = True
        agora = self._relogio.agora()
        with self._banco.exclusivo():
            with self._banco.transacao() as s:
                mercado = RepositorioMercado(s)
                for c in recebidas:
                    ativo = mercado.ativo_por_codigo(c.codigo)
                    invalida = (ativo is None or c.preco <= 0 or c.volume < 0
                                or c.instante > agora + timedelta(seconds=5))
                    atual = mercado.cotacao(ativo.id) if ativo else None
                    if invalida or (atual is not None and not atual.aceita_atualizacao(c.instante)):
                        resultado["descartadas"] += 1
                        self._auditoria.registrar(s, usuario="SISTEMA", acao="COTACAO_DESCARTADA",
                                                  entidade="ativo", entidade_id=c.codigo, resultado="ALERTA",
                                                  detalhes={"preco": str(c.preco), "instante": c.instante.isoformat()})
                        continue
                    if atual is None:
                        s.add(Cotacao(ativo.id, c.preco, c.volume, c.variacao, c.instante))
                    else:
                        atual.atualizar(c.preco, c.volume, c.variacao, c.instante)
                    resultado["atualizadas"] += 1
        return resultado

    def listar(self) -> list[dict]:
        """CSU02: preço, variação e volume com o horário da atualização; sinaliza defasagem."""
        agora = self._relogio.agora()
        with self._banco.transacao() as s:
            mercado = RepositorioMercado(s)
            cotacoes = {c.ativo_id: c for c in mercado.cotacoes()}
            linhas = []
            for ativo in mercado.ativos():
                c = cotacoes.get(ativo.id)
                linhas.append({
                    "codigo": ativo.codigo, "nome": ativo.nome, "tipo": ativo.tipo.value,
                    "lote_padrao": ativo.lote_padrao, "situacao": ativo.situacao.value,
                    "preco": str(c.preco) if c else None, "variacao": str(c.variacao) if c else None,
                    "volume": c.volume if c else None,
                    "atualizada_em": c.atualizada_em.isoformat() if c else None,
                    "idade_segundos": round(c.idade_segundos(agora), 1) if c else None,
                    "defasada": True if c is None else c.idade_segundos(agora) > self._config.cotacao_max_idade_s,
                })
            return linhas
