"""Rotas HTTP. Cada rota só autentica/autoriza, valida a entrada e delega ao serviço."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from ..dominio.excecoes import AcessoNegadoError, NaoEncontradoError
from ..dominio.usuarios import Usuario
from ..integracoes.simuladores import BolsaSimulada, NotificadorSimulado, ProvedorCotacoesSimulado
from ..servicos.ordens import DadosNovaOrdem
from ..servicos.sistema import Sistema
from . import esquemas as e
from .deps import COOKIE_SESSAO, exigir, obter_sistema, origem, usuario_atual

router = APIRouter(prefix="/api")


def _naive_utc(valor: datetime | None) -> datetime | None:
    if valor is not None and valor.tzinfo is not None:
        return valor.astimezone(timezone.utc).replace(tzinfo=None)
    return valor


def _usuario_json(u: Usuario) -> dict:
    return {"id": u.id, "login": u.login, "perfil": u.perfil.value, "nome_perfil": u.descricao_perfil(),
            "investidor_id": u.investidor_id, "permissoes": sorted(u.PERMISSOES)}


# ============================================================== saúde / autenticação
@router.get("/saude")
def saude(sistema: Sistema = Depends(obter_sistema)):
    return {"status": "ok" if sistema.banco.saudavel() else "degradado", "modo_simulacao": sistema.config.modo_simulacao,
            "novas_ordens_suspensas": sistema.risco.mercado_suspenso()}


@router.post("/auth/login")
def login(dados: e.LoginIn, request: Request, sistema: Sistema = Depends(obter_sistema)):
    d = sistema.autenticacao.iniciar_login(dados.login, dados.senha, origem(request))
    return {"desafio_id": d.desafio_id, "expira_em": d.expira_em.isoformat(),
            "validade_segundos": d.validade_segundos}


@router.post("/auth/mfa")
def mfa(dados: e.MfaIn, request: Request, resposta: Response, sistema: Sistema = Depends(obter_sistema)):
    usuario, token = sistema.autenticacao.validar_mfa(dados.desafio_id, dados.codigo, origem(request))
    resposta.set_cookie(COOKIE_SESSAO, token, httponly=True, samesite="strict",
                        max_age=sistema.config.sessao_validade_segundos)
    return {"token": token, "usuario": _usuario_json(usuario)}


@router.post("/auth/mfa/reenviar")
def reenviar(dados: e.ReenviarIn, request: Request, sistema: Sistema = Depends(obter_sistema)):
    d = sistema.autenticacao.reenviar_codigo(dados.desafio_id, origem(request))
    return {"desafio_id": d.desafio_id, "expira_em": d.expira_em.isoformat(), "validade_segundos": d.validade_segundos}


@router.post("/auth/logout")
def logout(request: Request, resposta: Response, usuario: Usuario = Depends(usuario_atual),
           sistema: Sistema = Depends(obter_sistema)):
    sistema.autenticacao.encerrar_sessao(usuario, origem(request))
    resposta.delete_cookie(COOKIE_SESSAO)
    return {"ok": True}


@router.get("/auth/eu")
def eu(usuario: Usuario = Depends(usuario_atual)):
    return _usuario_json(usuario)


@router.get("/simulador/codigo-mfa/{login}")
def codigo_mfa_simulado(login: str, sistema: Sistema = Depends(obter_sistema)):
    """Só em modo de simulação: equivale a 'olhar o celular'. Desligado fora do modo de simulação."""
    if not sistema.config.modo_simulacao or not isinstance(sistema.notificador, NotificadorSimulado):
        raise NaoEncontradoError("Recurso indisponível.")
    return {"codigo": sistema.notificador.ultimo_codigo(login)}


# ============================================================== investidor
@router.get("/cotacoes")
def cotacoes(_: Usuario = Depends(exigir("cotacao:ver")), sistema: Sistema = Depends(obter_sistema)):
    return sistema.cotacoes.listar()


@router.get("/carteira")
def carteira(usuario: Usuario = Depends(exigir("carteira:ver")), sistema: Sistema = Depends(obter_sistema)):
    return sistema.ordens.carteira(usuario)


@router.post("/ordens", status_code=201)
def enviar_ordem(dados: e.OrdemIn, request: Request, resposta: Response,
                 idempotency_key: str | None = Header(default=None),
                 usuario: Usuario = Depends(exigir("ordem:enviar")), sistema: Sistema = Depends(obter_sistema)):
    ordem = sistema.ordens.enviar(
        usuario, DadosNovaOrdem(dados.ativo, dados.lado, dados.modalidade, dados.quantidade, dados.preco,
                                idempotency_key), origem(request))
    if ordem.get("duplicada"):
        resposta.status_code = 200      # repetição: devolve a ordem original, sem criar outra
    return ordem


@router.get("/ordens")
def listar_ordens(estado: str | None = None, ativo: str | None = None, desde: datetime | None = None,
                  ate: datetime | None = None, limite: int = Query(200, ge=1, le=1000),
                  usuario: Usuario = Depends(usuario_atual), sistema: Sistema = Depends(obter_sistema)):
    return sistema.ordens.listar(usuario, estado=estado, ativo=ativo, desde=_naive_utc(desde),
                                 ate=_naive_utc(ate), limite=limite)


@router.get("/ordens/{ordem_id}")
def obter_ordem(ordem_id: str, usuario: Usuario = Depends(exigir("ordem:ver")),
                sistema: Sistema = Depends(obter_sistema)):
    return sistema.ordens.obter(usuario, ordem_id)


@router.patch("/ordens/{ordem_id}")
def alterar_ordem(ordem_id: str, dados: e.OrdemAlterarIn, request: Request,
                  usuario: Usuario = Depends(exigir("ordem:alterar")), sistema: Sistema = Depends(obter_sistema)):
    return sistema.ordens.alterar(usuario, ordem_id, dados.quantidade, dados.preco, origem(request))


@router.post("/ordens/{ordem_id}/cancelar")
def cancelar_ordem(ordem_id: str, request: Request, usuario: Usuario = Depends(exigir("ordem:cancelar")),
                   sistema: Sistema = Depends(obter_sistema)):
    return sistema.ordens.cancelar(usuario, ordem_id, origem(request))


@router.get("/notificacoes")
def notificacoes(usuario: Usuario = Depends(exigir("notificacao:ver")), sistema: Sistema = Depends(obter_sistema)):
    return sistema.consultas.notificacoes(usuario)


# ============================================================== operador de risco
@router.get("/risco/limites")
def listar_limites(usuario: Usuario = Depends(exigir("limite:definir")), sistema: Sistema = Depends(obter_sistema)):
    return sistema.risco.listar_limites(usuario)


@router.put("/risco/limites/{investidor_id}")
def definir_limites(investidor_id: int, dados: e.LimitesIn, request: Request,
                    usuario: Usuario = Depends(exigir("limite:definir")), sistema: Sistema = Depends(obter_sistema)):
    return sistema.risco.definir_limites(usuario, investidor_id, dados.max_por_ordem, dados.max_diario,
                                         origem(request))


@router.get("/risco/suspensoes")
def listar_suspensoes(usuario: Usuario = Depends(exigir("painel:ver")), sistema: Sistema = Depends(obter_sistema)):
    return sistema.risco.listar_suspensoes(usuario)


@router.post("/risco/suspensoes", status_code=201)
def acionar_suspensao(dados: e.SuspensaoIn, request: Request,
                      usuario: Usuario = Depends(exigir("suspensao:acionar")),
                      sistema: Sistema = Depends(obter_sistema)):
    return sistema.risco.acionar_suspensao(usuario, dados.escopo, dados.motivo, origem(request))


@router.post("/risco/suspensoes/encerrar")
def encerrar_suspensao(dados: e.EscopoIn, request: Request,
                       usuario: Usuario = Depends(exigir("suspensao:acionar")),
                       sistema: Sistema = Depends(obter_sistema)):
    return sistema.risco.encerrar_suspensao(usuario, dados.escopo, origem(request))


# ============================================================== painel (operador, admin, auditor)
@router.get("/painel")
def painel(usuario: Usuario = Depends(exigir("painel:ver")), sistema: Sistema = Depends(obter_sistema)):
    return sistema.consultas.painel(usuario)


@router.get("/painel/ordens-com-problema")
def ordens_com_problema(usuario: Usuario = Depends(exigir("painel:ver")), sistema: Sistema = Depends(obter_sistema)):
    return sistema.consultas.ordens_com_problema(usuario)


# ============================================================== administrador
@router.get("/admin/investidores")
def listar_investidores(usuario: Usuario = Depends(exigir("cadastro:investidor")),
                        sistema: Sistema = Depends(obter_sistema)):
    return sistema.cadastros.listar_investidores(usuario)


@router.post("/admin/investidores", status_code=201)
def criar_investidor(dados: e.InvestidorIn, request: Request,
                     usuario: Usuario = Depends(exigir("cadastro:investidor")),
                     sistema: Sistema = Depends(obter_sistema)):
    return sistema.cadastros.criar_investidor(usuario, origem=origem(request), **dados.model_dump())


@router.put("/admin/investidores/{investidor_id}")
def atualizar_investidor(investidor_id: int, dados: e.InvestidorNomeIn, request: Request,
                         usuario: Usuario = Depends(exigir("cadastro:investidor")),
                         sistema: Sistema = Depends(obter_sistema)):
    return sistema.cadastros.atualizar_investidor(usuario, investidor_id, dados.nome, origem(request))


@router.post("/admin/investidores/{investidor_id}/situacao")
def situacao_investidor(investidor_id: int, dados: e.SituacaoIn, request: Request,
                        usuario: Usuario = Depends(exigir("cadastro:investidor")),
                        sistema: Sistema = Depends(obter_sistema)):
    return sistema.cadastros.definir_situacao_investidor(usuario, investidor_id, dados.ativo, origem(request))


@router.post("/admin/investidores/{investidor_id}/deposito")
def depositar(investidor_id: int, dados: e.DepositoIn, request: Request,
              usuario: Usuario = Depends(exigir("cadastro:investidor")), sistema: Sistema = Depends(obter_sistema)):
    return sistema.cadastros.depositar(usuario, investidor_id, dados.valor, origem(request))


@router.get("/admin/ativos")
def listar_ativos(usuario: Usuario = Depends(exigir("cotacao:ver")), sistema: Sistema = Depends(obter_sistema)):
    return sistema.cadastros.listar_ativos(usuario)


@router.post("/admin/ativos", status_code=201)
def criar_ativo(dados: e.AtivoIn, request: Request, usuario: Usuario = Depends(exigir("cadastro:ativo")),
                sistema: Sistema = Depends(obter_sistema)):
    return sistema.cadastros.criar_ativo(usuario, origem=origem(request), **dados.model_dump())


@router.patch("/admin/ativos/{codigo}")
def atualizar_ativo(codigo: str, dados: e.AtivoAtualizarIn, request: Request,
                    usuario: Usuario = Depends(exigir("cadastro:ativo")), sistema: Sistema = Depends(obter_sistema)):
    return sistema.cadastros.atualizar_ativo(usuario, codigo, origem=origem(request), **dados.model_dump())


@router.get("/admin/usuarios")
def listar_usuarios(usuario: Usuario = Depends(exigir("perfil:gerenciar")), sistema: Sistema = Depends(obter_sistema)):
    return sistema.cadastros.listar_usuarios(usuario)


@router.post("/admin/usuarios", status_code=201)
def criar_usuario_interno(dados: e.UsuarioInternoIn, request: Request,
                          usuario: Usuario = Depends(exigir("perfil:gerenciar")),
                          sistema: Sistema = Depends(obter_sistema)):
    return sistema.cadastros.criar_usuario_interno(usuario, origem=origem(request), **dados.model_dump())


@router.put("/admin/usuarios/{usuario_id}/perfil")
def alterar_perfil(usuario_id: int, dados: e.PerfilIn, request: Request,
                   usuario: Usuario = Depends(exigir("perfil:gerenciar")), sistema: Sistema = Depends(obter_sistema)):
    return sistema.cadastros.alterar_perfil(usuario, usuario_id, dados.perfil, origem(request))


@router.post("/admin/usuarios/{usuario_id}/situacao")
def situacao_usuario(usuario_id: int, dados: e.SituacaoUsuarioIn, request: Request,
                     usuario: Usuario = Depends(exigir("perfil:gerenciar")),
                     sistema: Sistema = Depends(obter_sistema)):
    return sistema.cadastros.definir_situacao_usuario(usuario, usuario_id, ativo=dados.ativo,
                                                      desbloquear=dados.desbloquear, origem=origem(request))


# ============================================================== auditor
@router.get("/auditoria")
def auditoria(desde: datetime | None = None, ate: datetime | None = None, usuario: str | None = None,
              acao: str | None = None, ordem_id: str | None = None, limite: int = Query(500, ge=1, le=2000),
              request: Request = None, auditor: Usuario = Depends(exigir("auditoria:consultar")),
              sistema: Sistema = Depends(obter_sistema)):
    return sistema.consultas.consultar_auditoria(
        auditor, desde=_naive_utc(desde), ate=_naive_utc(ate), usuario=usuario, acao=acao, ordem_id=ordem_id,
        limite=limite, origem=origem(request))


@router.post("/auditoria/verificar")
def verificar_auditoria(request: Request, desde: datetime | None = None, ate: datetime | None = None,
                        auditor: Usuario = Depends(exigir("auditoria:consultar")),
                        sistema: Sistema = Depends(obter_sistema)):
    return sistema.consultas.verificar_integridade(auditor, _naive_utc(desde), _naive_utc(ate), origem(request))


# ============================================================== simulação de falhas (demonstração)
def _exigir_simulacao(sistema: Sistema) -> None:
    if not sistema.config.modo_simulacao:
        raise AcessoNegadoError("O painel de simulação está desabilitado.")


@router.post("/simulacao/bolsa")
def simular_bolsa(dados: e.SimulacaoBolsaIn, request: Request,
                  usuario: Usuario = Depends(exigir("simulacao:operar")), sistema: Sistema = Depends(obter_sistema)):
    _exigir_simulacao(sistema)
    bolsa = sistema.bolsa
    if not isinstance(bolsa, BolsaSimulada):
        raise AcessoNegadoError("A Bolsa configurada não é simulada.")
    for campo, valor in dados.model_dump(exclude_none=True).items():
        setattr(bolsa, campo, valor)
    _auditar_simulacao(sistema, usuario, "SIMULACAO_BOLSA", dados.model_dump(exclude_none=True), request)
    return sistema.status_integracoes()


@router.post("/simulacao/cotacoes")
def simular_provedor(dados: e.SimulacaoProvedorIn, request: Request,
                     usuario: Usuario = Depends(exigir("simulacao:operar")), sistema: Sistema = Depends(obter_sistema)):
    _exigir_simulacao(sistema)
    if not isinstance(sistema.provedor, ProvedorCotacoesSimulado):
        raise AcessoNegadoError("O provedor configurado não é simulado.")
    for campo, valor in dados.model_dump(exclude_none=True).items():
        setattr(sistema.provedor, campo, valor)
    _auditar_simulacao(sistema, usuario, "SIMULACAO_COTACOES", dados.model_dump(exclude_none=True), request)
    return sistema.status_integracoes()


@router.post("/simulacao/notificador")
def simular_notificador(dados: e.SimulacaoNotificadorIn, request: Request,
                        usuario: Usuario = Depends(exigir("simulacao:operar")),
                        sistema: Sistema = Depends(obter_sistema)):
    _exigir_simulacao(sistema)
    if not isinstance(sistema.notificador, NotificadorSimulado):
        raise AcessoNegadoError("O notificador configurado não é simulado.")
    sistema.notificador.falhar = dados.falhar
    _auditar_simulacao(sistema, usuario, "SIMULACAO_NOTIFICADOR", {"falhar": dados.falhar}, request)
    return sistema.status_integracoes()


@router.post("/simulacao/ciclo")
def executar_ciclo(usuario: Usuario = Depends(exigir("simulacao:operar")), sistema: Sistema = Depends(obter_sistema)):
    """Executa imediatamente um ciclo de processamento (útil para demonstrações passo a passo)."""
    _exigir_simulacao(sistema)
    return sistema.tick()


def _auditar_simulacao(sistema: Sistema, usuario: Usuario, acao: str, detalhes: dict, request: Request) -> None:
    with sistema.banco.exclusivo(), sistema.banco.transacao() as s:
        sistema.auditoria.registrar(s, usuario=usuario.login, perfil=usuario.perfil.value, acao=acao,
                                    origem=origem(request), detalhes=detalhes)
