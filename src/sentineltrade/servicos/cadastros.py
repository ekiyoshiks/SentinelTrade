"""CSU09 Manter Investidores e Contas · CSU10 Manter Ativos · CSU11 Gerenciar Perfis de Acesso."""
from __future__ import annotations

from decimal import Decimal
from typing import Callable

from sqlalchemy import update

from ..config import Configuracoes
from ..dominio.carteira import Conta
from ..dominio.estados import ESTADOS_ATIVOS
from ..dominio.excecoes import (AcessoNegadoError, ConflitoError, NaoEncontradoError, ValidacaoEntradaError)
from ..dominio.mercado import Ativo, TipoAtivo
from ..dominio.relogio import Relogio
from ..dominio.risco import LimiteRisco
from ..dominio.usuarios import CadastroInvestidor, Perfil, Usuario, criar_usuario
from ..persistencia.banco import Banco
from ..persistencia.mapeamento import Usuario as _UsuarioMapeado  # noqa: F401
from ..persistencia.repositorios import (RepositorioCadastros, RepositorioMercado, RepositorioOrdens,
                                         RepositorioUsuarios)
from ..persistencia.tabelas import usuarios as tabela_usuarios
from .auditoria import AuditoriaService
from .autenticacao import AutenticacaoService

# Alçada do Administrador: perfis que ele pode conceder a usuários internos.
PERFIS_CONCEDIVEIS = {Perfil.OPERADOR_RISCO, Perfil.AUDITOR}


class CadastroService:
    def __init__(self, banco: Banco, relogio: Relogio, config: Configuracoes, auditoria: AuditoriaService,
                 autenticacao: AutenticacaoService,
                 registrar_preco_inicial: Callable[[str, Decimal], None] | None = None):
        self._banco, self._relogio, self._config = banco, relogio, config
        self._auditoria, self._auth = auditoria, autenticacao
        self._registrar_preco = registrar_preco_inicial

    @staticmethod
    def _exigir(usuario: Usuario, permissao: str) -> None:
        if not usuario.pode(permissao):
            raise AcessoNegadoError("Seu perfil não tem permissão para esta operação.")

    def _auditar(self, s, admin: Usuario, acao: str, entidade: str, entidade_id, origem: str, detalhes=None):
        self._auditoria.registrar(s, usuario=admin.login, perfil=admin.perfil.value, acao=acao,
                                  entidade=entidade, entidade_id=str(entidade_id), origem=origem,
                                  detalhes=detalhes)

    # ================================================================== CSU09
    def criar_investidor(self, admin: Usuario, *, nome: str, documento: str, login: str, senha: str,
                         saldo_inicial: Decimal = Decimal("0"), max_por_ordem: Decimal = Decimal("50000"),
                         max_diario: Decimal = Decimal("200000"), origem: str = "API") -> dict:
        self._exigir(admin, "cadastro:investidor")
        nome, documento, login = nome.strip(), documento.strip(), login.strip()
        if not nome or not documento or not login:
            raise ValidacaoEntradaError("Nome, documento e login são obrigatórios.")
        senha_hash = self._auth.gerar_hash_senha(senha)          # RN10
        with self._banco.exclusivo():
            with self._banco.transacao() as s:
                cad, usuarios = RepositorioCadastros(s), RepositorioUsuarios(s)
                if cad.investidor_por_documento(documento) or usuarios.por_login(login):
                    raise ConflitoError("Documento ou login já cadastrado.")
                investidor = CadastroInvestidor(nome, documento)
                s.add(investidor)
                s.flush()
                s.add(Conta(investidor.id, saldo_inicial))
                limite = LimiteRisco(investidor.id, Decimal("1"), Decimal("1"))
                limite.definir(max_por_ordem, max_diario, self._config.teto_corretora_ordem,
                               self._config.teto_corretora_dia)
                s.add(limite)
                s.add(criar_usuario(Perfil.INVESTIDOR, login, senha_hash, investidor_id=investidor.id))
                self._auditar(s, admin, "INVESTIDOR_CRIADO", "investidor", investidor.id, origem,
                              {"login": login, "saldo_inicial": str(saldo_inicial)})
                return {"id": investidor.id, "nome": nome, "login": login}

    def listar_investidores(self, admin: Usuario) -> list[dict]:
        self._exigir(admin, "cadastro:investidor")
        with self._banco.transacao() as s:
            cad, usuarios = RepositorioCadastros(s), RepositorioUsuarios(s)
            linhas = []
            for i in cad.investidores():
                conta, usuario = cad.conta_do_investidor(i.id), usuarios.do_investidor(i.id)
                linhas.append({"id": i.id, "nome": i.nome, "documento": i.documento, "ativo": i.ativo,
                               "login": usuario.login if usuario else None,
                               "saldo": str(conta.saldo) if conta else None,
                               "reservado": str(conta.reservado) if conta else None})
            return linhas

    def atualizar_investidor(self, admin: Usuario, investidor_id: int, nome: str, origem: str = "API") -> dict:
        self._exigir(admin, "cadastro:investidor")
        if not nome.strip():
            raise ValidacaoEntradaError("Nome é obrigatório.")
        with self._banco.exclusivo(), self._banco.transacao() as s:
            inv = RepositorioCadastros(s).investidor(investidor_id)
            if inv is None:
                raise NaoEncontradoError("Investidor não encontrado.")
            inv.nome = nome.strip()
            self._auditar(s, admin, "INVESTIDOR_ALTERADO", "investidor", investidor_id, origem)
            return {"id": inv.id, "nome": inv.nome}

    def definir_situacao_investidor(self, admin: Usuario, investidor_id: int, ativo: bool,
                                    origem: str = "API") -> dict:
        self._exigir(admin, "cadastro:investidor")
        with self._banco.exclusivo(), self._banco.transacao() as s:
            cad = RepositorioCadastros(s)
            inv = cad.investidor(investidor_id)
            if inv is None:
                raise NaoEncontradoError("Investidor não encontrado.")
            usuario = RepositorioUsuarios(s).do_investidor(investidor_id)
            if not ativo:
                ordens_ativas = [o for o in RepositorioOrdens(s).listar(investidor_id=investidor_id, limite=1000)
                                 if o.estado in ESTADOS_ATIVOS]
                if ordens_ativas:
                    raise ConflitoError("Investidor com ordens ativas não pode ser desativado.")
                inv.desativar()
                if usuario:
                    usuario.desativar()
            else:
                inv.reativar()
                if usuario:
                    usuario.reativar()
            self._auditar(s, admin, "INVESTIDOR_ATIVADO" if ativo else "INVESTIDOR_DESATIVADO",
                          "investidor", investidor_id, origem)
            return {"id": inv.id, "ativo": inv.ativo}

    def depositar(self, admin: Usuario, investidor_id: int, valor: Decimal, origem: str = "API") -> dict:
        self._exigir(admin, "cadastro:investidor")
        with self._banco.exclusivo(), self._banco.transacao() as s:
            conta = RepositorioCadastros(s).conta_do_investidor(investidor_id)
            if conta is None:
                raise NaoEncontradoError("Conta não encontrada.")
            conta.depositar(valor)
            self._auditar(s, admin, "DEPOSITO_SIMULADO", "conta", conta.id, origem, {"valor": str(valor)})
            return {"saldo": str(conta.saldo)}

    # ================================================================== CSU10
    def listar_ativos(self, usuario: Usuario) -> list[dict]:
        self._exigir(usuario, "cotacao:ver")
        with self._banco.transacao() as s:
            return [{"id": a.id, "codigo": a.codigo, "nome": a.nome, "tipo": a.tipo.value,
                     "lote_padrao": a.lote_padrao, "situacao": a.situacao.value}
                    for a in RepositorioMercado(s).ativos()]

    def criar_ativo(self, admin: Usuario, *, codigo: str, nome: str, tipo: str, lote_padrao: int,
                    preco_inicial: Decimal, origem: str = "API") -> dict:
        self._exigir(admin, "cadastro:ativo")
        codigo = codigo.strip().upper()
        if not codigo or not nome.strip() or lote_padrao <= 0 or preco_inicial <= 0:
            raise ValidacaoEntradaError("Código, nome, lote e preço inicial válidos são obrigatórios.")
        try:
            tipo_ativo = TipoAtivo(tipo.upper())
        except ValueError:
            raise ValidacaoEntradaError("Tipo deve ser ACAO, ETF ou FII.")
        with self._banco.exclusivo(), self._banco.transacao() as s:
            if RepositorioMercado(s).ativo_por_codigo(codigo):
                raise ConflitoError("Código de ativo já cadastrado.")
            ativo = Ativo(codigo, nome.strip(), tipo_ativo, lote_padrao)
            s.add(ativo)
            s.flush()
            self._auditar(s, admin, "ATIVO_CRIADO", "ativo", codigo, origem)
        if self._registrar_preco:
            self._registrar_preco(codigo, preco_inicial)
        return {"codigo": codigo}

    def atualizar_ativo(self, admin: Usuario, codigo: str, *, nome: str | None = None,
                        lote_padrao: int | None = None, situacao: str | None = None,
                        origem: str = "API") -> dict:
        self._exigir(admin, "cadastro:ativo")
        with self._banco.exclusivo(), self._banco.transacao() as s:
            ativo = RepositorioMercado(s).ativo_por_codigo(codigo)
            if ativo is None:
                raise NaoEncontradoError("Ativo não encontrado.")
            if lote_padrao is not None and lote_padrao <= 0:
                raise ValidacaoEntradaError("Lote deve ser positivo.")
            ativo.atualizar(nome or ativo.nome, lote_padrao or ativo.lote_padrao)
            if situacao:
                {"SUSPENSO": ativo.suspender, "NEGOCIAVEL": ativo.reativar}.get(
                    situacao.upper(), lambda: (_ for _ in ()).throw(
                        ValidacaoEntradaError("Situação deve ser NEGOCIAVEL ou SUSPENSO.")))()
            self._auditar(s, admin, "ATIVO_ALTERADO", "ativo", ativo.codigo, origem,
                          {"situacao": ativo.situacao.value, "lote": ativo.lote_padrao})
            return {"codigo": ativo.codigo, "situacao": ativo.situacao.value}

    # ================================================================== CSU11
    def listar_usuarios(self, admin: Usuario) -> list[dict]:
        self._exigir(admin, "perfil:gerenciar")
        agora = self._relogio.agora()
        with self._banco.transacao() as s:
            return [{"id": u.id, "login": u.login, "perfil": u.perfil.value, "ativo": u.ativo,
                     "bloqueado": u.esta_bloqueado(agora), "investidor_id": u.investidor_id}
                    for u in RepositorioUsuarios(s).listar()]

    def criar_usuario_interno(self, admin: Usuario, *, login: str, senha: str, perfil: str,
                              origem: str = "API") -> dict:
        self._exigir(admin, "perfil:gerenciar")
        alvo = self._perfil_concedivel(perfil)
        senha_hash = self._auth.gerar_hash_senha(senha)
        with self._banco.exclusivo(), self._banco.transacao() as s:
            if RepositorioUsuarios(s).por_login(login.strip()):
                raise ConflitoError("Login já cadastrado.")
            s.add(criar_usuario(alvo, login.strip(), senha_hash))
            self._auditar(s, admin, "USUARIO_CRIADO", "usuario", login.strip(), origem, {"perfil": alvo.value})
            return {"login": login.strip(), "perfil": alvo.value}

    @staticmethod
    def _perfil_concedivel(perfil: str) -> Perfil:
        try:
            alvo = Perfil(perfil.upper())
        except ValueError:
            raise ValidacaoEntradaError("Perfil inválido.")
        if alvo not in PERFIS_CONCEDIVEIS:
            raise AcessoNegadoError("Perfil acima da alçada do Administrador.")
        return alvo

    def alterar_perfil(self, admin: Usuario, usuario_id: int, perfil: str, origem: str = "API") -> dict:
        self._exigir(admin, "perfil:gerenciar")
        alvo = self._perfil_concedivel(perfil)
        with self._banco.exclusivo(), self._banco.transacao() as s:
            usuario = RepositorioUsuarios(s).por_id(usuario_id)
            if usuario is None:
                raise NaoEncontradoError("Usuário não encontrado.")
            if usuario.perfil not in PERFIS_CONCEDIVEIS:
                raise AcessoNegadoError("Este usuário está fora da alçada do Administrador.")
            anterior, login = usuario.perfil, usuario.login
            s.execute(update(tabela_usuarios).where(tabela_usuarios.c.id == usuario_id).values(perfil=alvo.value))
            s.expunge(usuario)     # a instância antiga tem a classe do perfil anterior (mapeamento polimórfico)
            s.expire_all()
            self._auditar(s, admin, "PERFIL_ALTERADO", "usuario", login, origem,
                          {"de": anterior.value, "para": alvo.value})
            return {"login": login, "perfil": alvo.value}

    def definir_situacao_usuario(self, admin: Usuario, usuario_id: int, *, ativo: bool | None = None,
                                 desbloquear: bool = False, origem: str = "API") -> dict:
        self._exigir(admin, "perfil:gerenciar")
        with self._banco.exclusivo(), self._banco.transacao() as s:
            usuario = RepositorioUsuarios(s).por_id(usuario_id)
            if usuario is None:
                raise NaoEncontradoError("Usuário não encontrado.")
            if usuario.id == admin.id and ativo is False:
                raise ConflitoError("Você não pode desativar o próprio usuário.")
            if desbloquear:
                usuario.desbloquear()
            if ativo is True:
                usuario.reativar()
            elif ativo is False:
                usuario.desativar()
            self._auditar(s, admin, "USUARIO_SITUACAO", "usuario", usuario.login, origem,
                          {"ativo": usuario.ativo, "desbloqueado": desbloquear})
            return {"login": usuario.login, "ativo": usuario.ativo}
