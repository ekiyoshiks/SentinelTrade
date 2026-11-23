"""Dados fictícios de demonstração (nenhum dado real, nenhuma credencial real)."""
from __future__ import annotations

import os
from decimal import Decimal

from .dominio.carteira import Conta, Posicao
from .dominio.mercado import Ativo, TipoAtivo
from .dominio.risco import LimiteRisco
from .dominio.usuarios import CadastroInvestidor, Perfil, criar_usuario
from .persistencia.repositorios import RepositorioMercado
from .servicos.sistema import Sistema

ATIVOS = [
    ("PETR4", "Petrobras PN", TipoAtivo.ACAO, 100), ("VALE3", "Vale ON", TipoAtivo.ACAO, 100),
    ("ITUB4", "Itaú Unibanco PN", TipoAtivo.ACAO, 100), ("BBAS3", "Banco do Brasil ON", TipoAtivo.ACAO, 100),
    ("MGLU3", "Magazine Luiza ON", TipoAtivo.ACAO, 100), ("BOVA11", "iShares Ibovespa", TipoAtivo.ETF, 10),
    ("HGLG11", "CSHG Logística", TipoAtivo.FII, 10), ("XPLG11", "XP Log", TipoAtivo.FII, 10),
]

INVESTIDORES = [
    # login, nome, documento fictício, saldo, limite/ordem, limite/dia, posições iniciais
    ("ana", "Ana Souza", "000.000.001-01", "250000", "100000", "500000", {"PETR4": 500, "VALE3": 300}),
    ("bruno", "Bruno Lima", "000.000.002-02", "120000", "50000", "200000", {"ITUB4": 400}),
    ("carla", "Carla Mendes", "000.000.003-03", "60000", "30000", "100000", {}),
]

INTERNOS = [("operador", Perfil.OPERADOR_RISCO), ("admin", Perfil.ADMINISTRADOR), ("auditor", Perfil.AUDITOR)]


def senha_demo() -> str:
    return os.environ.get("SEED_SENHA", "Orion@Demo2026")


def popular(sistema: Sistema) -> dict:
    """Cria ativos, usuários, contas, limites e posições de exemplo. Idempotente por login."""
    senha_hash = sistema.autenticacao.gerar_hash_senha(senha_demo())
    criados = []
    with sistema.banco.exclusivo(), sistema.banco.transacao() as s:
        mercado = RepositorioMercado(s)
        for codigo, nome, tipo, lote in ATIVOS:
            if mercado.ativo_por_codigo(codigo) is None:
                s.add(Ativo(codigo, nome, tipo, lote))
        s.flush()
        from .persistencia.repositorios import RepositorioUsuarios
        usuarios = RepositorioUsuarios(s)
        for login, nome, doc, saldo, max_ordem, max_dia, posicoes in INVESTIDORES:
            if usuarios.por_login(login):
                continue
            inv = CadastroInvestidor(nome, doc)
            s.add(inv)
            s.flush()
            conta = Conta(inv.id, Decimal(saldo))
            s.add(conta)
            s.flush()
            s.add(LimiteRisco(inv.id, Decimal(max_ordem), Decimal(max_dia)))
            s.add(criar_usuario(Perfil.INVESTIDOR, login, senha_hash, investidor_id=inv.id))
            for codigo, quantidade in posicoes.items():
                posicao = Posicao(conta.id, mercado.ativo_por_codigo(codigo).id)
                posicao.registrar_compra(quantidade, sistema.provedor_preco(codigo))
                s.add(posicao)
            criados.append(login)
        for login, perfil in INTERNOS:
            if not usuarios.por_login(login):
                s.add(criar_usuario(perfil, login, senha_hash))
                criados.append(login)
        sistema.auditoria.registrar(s, usuario="SISTEMA", acao="SEED", detalhes={"criados": criados})
    sistema.cotacoes.atualizar()   # primeira carga de cotações
    return {"usuarios_criados": criados}
