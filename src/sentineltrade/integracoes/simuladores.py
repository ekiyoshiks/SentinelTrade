"""Simuladores dos sistemas externos: Provedor de Cotações, Bolsa/Corretora e Notificação.

Cada simulador permite *injetar falhas* (provedor parado, Bolsa sem resposta, retorno
duplicado, falha de entrega) para demonstrar e testar os cenários de falha do doc 03.
"""
from __future__ import annotations

import random
import threading
from collections import deque
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from ..dominio.dinheiro import q2
from ..dominio.excecoes import BolsaRecusouError, IntegracaoError, IntegracaoTimeoutError
from ..dominio.relogio import Relogio
from .interfaces import (BolsaGateway, CotacaoRecebida, Notificador, PedidoBolsa, ProvedorCotacoes,
                         RespostaBolsa, RetornoBolsa, StatusBolsa, TipoRetorno)


# --------------------------------------------------------------------------- cotações
class ProvedorCotacoesSimulado(ProvedorCotacoes):
    """Gera cotações por passeio aleatório determinístico (seed)."""

    def __init__(self, relogio: Relogio, precos_iniciais: dict[str, Decimal], seed: int = 42):
        self._relogio = relogio
        self._rng = random.Random(seed)
        self._precos = {c: q2(p) for c, p in precos_iniciais.items()}
        self._abertura = dict(self._precos)
        self._volume = {c: 0 for c in precos_iniciais}
        self._lock = threading.RLock()
        self.pausado = False        # simula provedor fora do ar
        self.atraso_s = 0           # simula dados defasados (timestamp antigo)
        self.oscilar = True

    def registrar_ativo(self, codigo: str, preco: Decimal) -> None:
        with self._lock:
            self._precos[codigo] = q2(preco)
            self._abertura.setdefault(codigo, q2(preco))
            self._volume.setdefault(codigo, 0)

    def ultimo_preco(self, codigo: str) -> Decimal | None:
        with self._lock:
            return self._precos.get(codigo)

    def definir_preco(self, codigo: str, preco: Decimal) -> None:
        with self._lock:
            self._precos[codigo] = q2(preco)

    def obter(self) -> list[CotacaoRecebida]:
        with self._lock:
            if self.pausado:
                raise IntegracaoTimeoutError("Provedor de cotações sem resposta.")
            instante = self._relogio.agora() - timedelta(seconds=self.atraso_s)
            resultado = []
            for codigo, preco in self._precos.items():
                if self.oscilar:
                    passo = Decimal(str(round(self._rng.uniform(-0.006, 0.006), 5)))
                    preco = max(Decimal("0.50"), q2(preco * (Decimal("1") + passo)))
                    self._precos[codigo] = preco
                self._volume[codigo] += self._rng.randint(100, 5000) // 100 * 100
                variacao = q2((preco / self._abertura[codigo] - 1) * 100)
                resultado.append(CotacaoRecebida(codigo, preco, self._volume[codigo], variacao, instante))
            return resultado


# --------------------------------------------------------------------------- bolsa
@dataclass
class _OrdemNaBolsa:
    pedido: PedidoBolsa
    id_bolsa: str
    quantidade: int
    preco_limite: Decimal | None
    executada: int = 0
    situacao: str = "ABERTA"   # ABERTA | EXECUTADA | CANCELADA | REJEITADA


class BolsaSimulada(BolsaGateway):
    """Bolsa em memória. Ordens limitadas ficam abertas até o preço do mercado cruzar o limite."""

    def __init__(self, relogio: Relogio, provedor: ProvedorCotacoesSimulado, seed: int = 42):
        self._relogio = relogio
        self._provedor = provedor
        self._rng = random.Random(seed + 1)
        self._ordens: dict[str, _OrdemNaBolsa] = {}
        self._retornos: list[RetornoBolsa] = []
        self._contador = 0
        self._lock = threading.RLock()
        # --- controles de falha ---
        self.modo = "NORMAL"            # NORMAL | SEM_RESPOSTA | RESPOSTA_PERDIDA
        self.execucao_parcial = False   # executa a ordem em duas partes
        self.rejeitar_proximas = 0      # rejeita as próximas N ordens
        self.duplicar_retorno = False   # reentrega o próximo retorno duas vezes

    # --- util ----------------------------------------------------------------
    def _proximo_id(self, prefixo: str) -> str:
        self._contador += 1
        return f"{prefixo}-{self._contador:06d}"

    def _checar_resposta(self) -> None:
        if self.modo == "SEM_RESPOSTA":
            raise IntegracaoTimeoutError("A Bolsa não respondeu dentro do tempo limite.")

    def _emitir(self, chave: str, tipo: TipoRetorno, quantidade=0, preco=None, motivo=None) -> None:
        evento = RetornoBolsa(self._proximo_id("EV"), chave, tipo.value, quantidade, preco, motivo)
        self._retornos.append(evento)
        if self.duplicar_retorno:
            self._retornos.append(evento)
            self.duplicar_retorno = False

    # --- contrato ------------------------------------------------------------
    def enviar(self, pedido: PedidoBolsa) -> RespostaBolsa:
        with self._lock:
            self._checar_resposta()
            existente = self._ordens.get(pedido.chave)
            if existente:
                return RespostaBolsa(existente.id_bolsa, ja_conhecida=True)
            ordem = _OrdemNaBolsa(pedido, self._proximo_id("BX"), pedido.quantidade, pedido.preco_limite)
            self._ordens[pedido.chave] = ordem
            if self.rejeitar_proximas > 0:
                self.rejeitar_proximas -= 1
                ordem.situacao = "REJEITADA"
                self._emitir(pedido.chave, TipoRetorno.REJEICAO, motivo="Rejeitada pela Bolsa (simulação).")
            if self.modo == "RESPOSTA_PERDIDA":
                # a Bolsa recebeu, mas a confirmação se perdeu: o sistema só descobre consultando
                raise IntegracaoTimeoutError("A Bolsa não respondeu dentro do tempo limite.")
            return RespostaBolsa(ordem.id_bolsa)

    def alterar(self, chave: str, quantidade: int, preco_limite: Decimal | None) -> None:
        with self._lock:
            self._checar_resposta()
            ordem = self._ordens.get(chave)
            if ordem is None or ordem.situacao != "ABERTA" or quantidade < ordem.executada:
                raise BolsaRecusouError("A Bolsa recusou a alteração: ordem já executada ou encerrada.")
            ordem.quantidade = quantidade
            if preco_limite is not None:
                ordem.preco_limite = q2(preco_limite)

    def cancelar(self, chave: str) -> int:
        with self._lock:
            self._checar_resposta()
            ordem = self._ordens.get(chave)
            if ordem is None:
                return 0
            if ordem.situacao == "EXECUTADA":
                raise BolsaRecusouError("A Bolsa recusou o cancelamento: ordem já executada.")
            ordem.situacao = "CANCELADA"
            return ordem.executada

    def consultar(self, chave: str) -> StatusBolsa | None:
        with self._lock:
            self._checar_resposta()
            ordem = self._ordens.get(chave)
            return None if ordem is None else StatusBolsa(ordem.id_bolsa, ordem.situacao, ordem.executada)

    def coletar_retornos(self) -> list[RetornoBolsa]:
        with self._lock:
            self._checar_resposta()
            self._casar_ordens()
            return list(self._retornos)

    def confirmar_retorno(self, id_evento: str) -> None:
        with self._lock:
            self._retornos = [r for r in self._retornos if r.id_evento != id_evento]

    def saude(self) -> bool:
        return self.modo == "NORMAL"

    # --- casamento -------------------------------------------------------------
    def _casar_ordens(self) -> None:
        """Executa ordens abertas conforme o preço atual do mercado."""
        for chave, ordem in self._ordens.items():
            if ordem.situacao != "ABERTA":
                continue
            mercado = self._provedor.ultimo_preco(ordem.pedido.codigo_ativo)
            if mercado is None:
                continue
            compra = ordem.pedido.lado == "COMPRA"
            if ordem.pedido.modalidade == "MERCADO":
                preco = mercado
            else:
                limite = ordem.preco_limite
                if (compra and limite < mercado) or (not compra and limite > mercado):
                    continue  # limite ainda não atingido
                preco = min(limite, mercado) if compra else max(limite, mercado)
            restante = ordem.quantidade - ordem.executada
            if restante <= 0:
                continue
            lote = ordem.pedido.lote
            quantidade = restante
            if self.execucao_parcial and ordem.executada == 0 and restante >= 2 * lote:
                quantidade = (restante // 2) // lote * lote
            ordem.executada += quantidade
            total = ordem.executada >= ordem.quantidade
            ordem.situacao = "EXECUTADA" if total else "ABERTA"
            self._emitir(chave, TipoRetorno.EXECUCAO_TOTAL if total else TipoRetorno.EXECUCAO_PARCIAL,
                         quantidade, preco)


# --------------------------------------------------------------------------- notificação
class NotificadorSimulado(Notificador):
    def __init__(self) -> None:
        self.caixa: deque[dict] = deque(maxlen=200)
        self._codigos: dict[str, str] = {}
        self.falhar = False  # simula falha na entrega

    def entregar(self, destinatario: str, mensagem: str) -> None:
        if self.falhar:
            raise IntegracaoError("Falha na entrega da notificação (simulação).")
        self.caixa.appendleft({"destinatario": destinatario, "mensagem": mensagem})

    def enviar_codigo_mfa(self, login: str, codigo: str) -> None:
        self._codigos[login] = codigo
        self.caixa.appendleft({"destinatario": login, "mensagem": "Código de verificação enviado."})

    def ultimo_codigo(self, login: str) -> str | None:
        """Só para o modo de simulação: equivale a 'olhar o celular' do usuário."""
        return self._codigos.get(login)
