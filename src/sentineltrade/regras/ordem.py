"""Regras de negócio aplicadas na validação de ordens (RN01–RN07, RN09)."""
from __future__ import annotations

from decimal import Decimal

from ..dominio.excecoes import RegraNegocioError, TransicaoInvalidaError
from ..dominio.ordens import Lado
from .base import ContextoValidacao, RegraNegocio


class RN01SaldoSuficiente(RegraNegocio):
    codigo = "RN01"
    descricao = "Compra só é aceita se o saldo disponível cobrir o valor total estimado."

    def validar(self, ctx: ContextoValidacao) -> None:
        if ctx.ordem.lado is not Lado.COMPRA:
            return
        necessario = ctx.ordem.valor_a_reservar
        if necessario > ctx.conta.disponivel:
            raise RegraNegocioError(
                f"Saldo insuficiente: necessário R$ {necessario}, disponível R$ {ctx.conta.disponivel}.",
                codigo=self.codigo, rejeita_ordem=True,
                detalhes={"disponivel": str(ctx.conta.disponivel), "necessario": str(necessario)},
            )


class RN02PosicaoSuficiente(RegraNegocio):
    codigo = "RN02"
    descricao = "Venda só é aceita se a quantidade disponível em carteira cobrir a quantidade vendida."

    def validar(self, ctx: ContextoValidacao) -> None:
        if ctx.ordem.lado is not Lado.VENDA:
            return
        disponivel = ctx.posicao.disponivel if ctx.posicao else 0
        if ctx.ordem.quantidade_restante > disponivel:
            raise RegraNegocioError(
                f"Posição insuficiente: disponível {disponivel} (não há venda a descoberto).",
                codigo=self.codigo, rejeita_ordem=True, detalhes={"disponivel": disponivel},
            )


class RN03LimiteRisco(RegraNegocio):
    codigo = "RN03"
    descricao = "Valor da ordem e total do dia não podem ultrapassar os limites de risco."

    def validar(self, ctx: ContextoValidacao) -> None:
        if ctx.limite is None:
            raise RegraNegocioError(
                "Investidor sem limites de risco definidos; ordem recusada por segurança.",
                codigo=self.codigo, rejeita_ordem=True)
        ok, motivo = ctx.limite.comporta(ctx.ordem.valor_estimado, ctx.total_dia)
        if not ok:
            raise RegraNegocioError(motivo or "Limite de risco excedido.", codigo=self.codigo,
                                    rejeita_ordem=True)


class RN04MercadoAberto(RegraNegocio):
    codigo = "RN04"
    descricao = "Ordens só são enviadas com mercado aberto e ativo negociável."

    def validar(self, ctx: ContextoValidacao) -> None:
        if not ctx.ativo.negociavel:
            raise RegraNegocioError(
                f"Ativo {ctx.ativo.codigo} está suspenso para negociação.",
                codigo=self.codigo, rejeita_ordem=True)
        if not ctx.mercado_aberto:
            raise RegraNegocioError(
                f"Mercado fechado. Próximo horário de negociação: {ctx.proximo_pregao}.",
                codigo=self.codigo, rejeita_ordem=True)


class RN05LoteMultiplo(RegraNegocio):
    codigo = "RN05"
    descricao = "A quantidade deve ser múltipla do lote padrão do ativo."

    def validar(self, ctx: ContextoValidacao) -> None:
        if not ctx.ativo.quantidade_valida(ctx.ordem.quantidade):
            raise RegraNegocioError(
                f"Quantidade deve ser múltipla do lote padrão ({ctx.ativo.lote_padrao}).",
                codigo=self.codigo, detalhes={"lote_padrao": ctx.ativo.lote_padrao})


class RN06PrecoLimitadaNaFaixa(RegraNegocio):
    codigo = "RN06"
    descricao = "Preço de ordem limitada > 0 e dentro da faixa em torno da última cotação."

    def validar(self, ctx: ContextoValidacao) -> None:
        if not ctx.ordem.exige_preco_na_faixa():
            return
        preco = ctx.ordem.preco_limite
        if preco is None or preco <= 0:
            raise RegraNegocioError("O preço da ordem limitada deve ser maior que zero.", codigo=self.codigo)
        if ctx.cotacao is None:
            raise RegraNegocioError("Sem cotação de referência para validar o preço.", codigo=self.codigo)
        faixa = ctx.config.faixa_preco_limitada
        ref = ctx.cotacao.preco
        minimo, maximo = ref * (Decimal("1") - faixa), ref * (Decimal("1") + faixa)
        if not (minimo <= preco <= maximo):
            raise RegraNegocioError(
                f"Preço fora da faixa permitida (R$ {minimo:.2f} a R$ {maximo:.2f}).",
                codigo=self.codigo, detalhes={"minimo": f"{minimo:.2f}", "maximo": f"{maximo:.2f}"})


class RN07CotacaoAtualizada(RegraNegocio):
    codigo = "RN07"
    descricao = "Ordem a mercado só é aceita com cotação de no máximo 5 segundos."

    def validar(self, ctx: ContextoValidacao) -> None:
        if not ctx.ordem.exige_cotacao_fresca():
            return
        if ctx.cotacao is None:
            raise RegraNegocioError("Sem cotação disponível; use ordem limitada.", codigo=self.codigo)
        idade = ctx.cotacao.idade_segundos(ctx.agora)
        if idade > ctx.config.cotacao_max_idade_s:
            raise RegraNegocioError(
                f"Cotação desatualizada ({idade:.0f}s). Ordem a mercado recusada; sugerimos ordem limitada.",
                codigo=self.codigo, detalhes={"idade_segundos": round(idade, 1)})


class RN09OrdemAlteravel(RegraNegocio):
    codigo = "RN09"
    descricao = "Só podem ser alteradas ou canceladas ordens Validada, Enviada ou Parcialmente Executada."

    def validar(self, ctx: ContextoValidacao) -> None:
        if not ctx.ordem.alteravel:
            raise TransicaoInvalidaError(
                f"Ordem em {ctx.ordem.estado.value} não pode ser alterada ou cancelada.")


class ValidadorOrdem:
    """Executa a cadeia de regras na ordem do CSU04 (passo 5).

    Erros de entrada (RN05–RN07) vêm primeiro e não geram ordem; depois mercado, saldo/posição
    e limites, que geram ordem Rejeitada.
    """

    def __init__(self, regras: list[RegraNegocio]):
        self._regras = list(regras)

    @property
    def regras(self) -> list[RegraNegocio]:
        return list(self._regras)

    def validar(self, ctx: ContextoValidacao) -> None:
        for regra in self._regras:
            regra.validar(ctx)

    @classmethod
    def padrao(cls) -> "ValidadorOrdem":
        return cls([
            RN05LoteMultiplo(), RN06PrecoLimitadaNaFaixa(), RN07CotacaoAtualizada(),
            RN04MercadoAberto(), RN01SaldoSuficiente(), RN02PosicaoSuficiente(), RN03LimiteRisco(),
        ])
