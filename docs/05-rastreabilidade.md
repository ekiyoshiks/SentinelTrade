# 05 — Rastreabilidade

Liga **requisito → caso de uso → regra de negócio → código → teste**. Caminhos de código relativos a `src/sentineltrade/`; testes em `tests/`. Os critérios detalhados estão em [04-criterios-de-aceitacao.md](04-criterios-de-aceitacao.md) e o diagrama em [diagramas/casos-de-uso.puml](diagramas/casos-de-uso.puml).

## 1. Casos de uso → requisitos → implementação → testes

| Caso de uso | Requisitos | Regras | Implementação (Etapa 2) | Testes |
|---|---|---|---|---|
| CSU01 Autenticar com MFA | RF-01 | RN10, RN11 | `servicos/autenticacao.py`, `regras/senha.py`, `api/deps.py` | `test_autenticacao_cadastros_auditoria.py` (login, MFA, bloqueio, senha, token) |
| CSU02 Consultar Cotações | RF-05 | RN07 | `servicos/cotacoes.py`, `GET /api/cotacoes`, dashboard "Mercado" | `test_api.py`; `test_ordens_regras.py::test_rn07_*` |
| CSU03 Consultar Carteira | RF-07 | — | `servicos/ordens.py::carteira`, `GET /api/carteira` | `test_ordens_regras.py::test_compra_a_mercado_executa_e_debita_saldo` |
| CSU04 Enviar Ordem | RF-08, RF-09, RF-12, RF-20 | RN01–RN08, RN13 | `servicos/ordens.py::enviar`, `regras/ordem.py`, `dominio/ordens.py` | `test_ordens_regras.py`, `test_integracao_bolsa.py`, `test_api.py` |
| CSU05 Alterar Ordem | RF-11 | RN01–RN07, RN09 | `servicos/ordens.py::alterar` | `test_ordens_regras.py::test_alterar_*`, `::test_rn09_*` |
| CSU06 Cancelar Ordem | RF-10 | RN09, RN13 | `servicos/ordens.py::cancelar` | `test_ordens_regras.py::test_cancelar_*`, `test_integracao_bolsa.py::test_cancelamento_*` |
| CSU07 Acompanhar Status | RF-13 | RN13 | `servicos/ordens.py::obter`, `ordens_historico` | `test_ordens_regras.py::test_historico_*`, `::test_nao_ve_nem_altera_*` |
| CSU08 Histórico de Operações | RF-16 | RN13 | `servicos/ordens.py::listar`, tabela `operacoes` | `test_ordens_regras.py` (listagens por investidor) |
| CSU09 Investidores e Contas | RF-03 | RN10 | `servicos/cadastros.py` | `test_autenticacao_cadastros_auditoria.py::test_admin_*`, `::test_login_duplicado_*`, `::test_investidor_com_ordem_ativa_*` |
| CSU10 Ativos | RF-04 | RN04 | `servicos/cadastros.py` | `::test_admin_deposita_e_cria_ativo`, `::test_ativo_suspenso_nao_aceita_ordens` |
| CSU11 Perfis de Acesso | RF-02 | — | `servicos/cadastros.py`, `dominio/usuarios.py` | `::test_admin_altera_perfil_e_desbloqueia_usuario`, `::test_admin_nao_concede_perfil_administrador` |
| CSU12 Limites de Risco | RF-18 | RN03 | `servicos/risco.py`, `dominio/risco.py` | `test_ordens_regras.py::test_rn03_*` |
| CSU13 Indisponibilidade Segura | RF-19 | — | `servicos/risco.py`, `GET /api/saude` | `test_integracao_bolsa.py::test_suspensao_*`, `::test_erro_inesperado_*` |
| CSU14 Registros de Auditoria | RF-17 | RN12 | `servicos/auditoria.py`, `servicos/consultas.py`, gatilhos SQL | `test_autenticacao_cadastros_auditoria.py::test_*auditoria*`, `::test_adulteracao_*` |
| CSU15 Atualizar Cotações | RF-06 | RN07 | `integracoes/simuladores.py::ProvedorCotacoesSimulado`, `servicos/cotacoes.py` | `test_integracao_bolsa.py::test_cotacoes_defasadas_nao_derrubam_o_sistema` |
| CSU16 Retorno da Bolsa | RF-12, RF-13, RF-14 | RN08, RN09 | `servicos/retorno_bolsa.py` | `test_integracao_bolsa.py::test_execucao_parcial_*`, `::test_retorno_duplicado_*`, `::test_bolsa_rejeita_*` |
| CSU17 Notificar Investidor | RF-15 | — | `servicos/notificacoes.py`, `servicos/fila.py` | `test_integracao_bolsa.py::test_esgotadas_as_tentativas_*` |
| CSU18 Reprocessar Pendentes | RF-21 | RN08 | `servicos/transmissao.py::reprocessar_pendentes` | `test_integracao_bolsa.py::test_bolsa_sem_resposta_*`, `::test_resposta_perdida_*` |

## 2. Regras de negócio → implementação

| Regra | Descrição | Classe / local | Teste |
|---|---|---|---|
| RN01 | Saldo suficiente (compra) | `regras/ordem.py::RN01SaldoSuficiente` | `test_rn01_*` |
| RN02 | Posição suficiente (venda) | `RN02PosicaoSuficiente` | `test_rn02_*` |
| RN03 | Limite de risco por ordem e por dia | `RN03LimiteRisco` | `test_rn03_*` |
| RN04 | Mercado aberto e ativo negociável | `RN04MercadoAberto`, `regras/calendario.py` | `test_rn04_*` |
| RN05 | Quantidade múltipla do lote | `RN05LoteMultiplo` | `test_rn05_*` |
| RN06 | Preço da limitada dentro da faixa | `RN06PrecoLimitadaNaFaixa` | `test_rn06_*` |
| RN07 | Cotação atualizada (ordem a mercado) | `RN07CotacaoAtualizada` | `test_rn07_*` |
| RN08 | Idempotência / sem duplicidade | `UNIQUE(chave_idempotencia)` em `ordens`; `eventos_bolsa` | `test_rn08_*`, `test_retorno_duplicado_*` |
| RN09 | Estados que permitem alterar/cancelar | `dominio/estados.py`, `RN09OrdemAlteravel` | `test_estados.py`, `test_rn09_*` |
| RN10 | Política de senha (≥12, letras e números) | `regras/senha.py::RN10PoliticaSenha` | `test_rn10_*` |
| RN11 | Bloqueio após tentativas inválidas | `servicos/autenticacao.py` | `test_rn11_*` |
| RN12 | Auditoria imutável com hash encadeado | `servicos/auditoria.py`, gatilhos em `persistencia/banco.py` | `test_auditoria_e_append_only_*`, `test_adulteracao_*` |
| RN13 | Investidor só acessa as próprias ordens | `servicos/ordens.py::_carregar_do_investidor` | `test_nao_ve_nem_altera_*` |

## 3. Cenários de falha (03 — visão sistêmica) → resposta implementada

| Cenário | Resposta projetada | Onde | Teste |
|---|---|---|---|
| Bolsa não responde | Time-out, Falha, consulta antes de reenviar, mesma chave | `servicos/transmissao.py` | `test_bolsa_sem_resposta_*`, `test_resposta_perdida_*` |
| Duplo clique em "confirmar" | Idempotência | `ordens.chave_idempotencia` | `test_rn08_*`, `test_criar_ordem_201_e_duplicada_200` |
| Retorno da Bolsa duplicado | Processamento idempotente | `eventos_bolsa` (`id_evento` único) | `test_retorno_duplicado_*` |
| Provedor de cotações cai | Bloqueio de ordem a mercado e sinalização | `RN07`, `defasada` na API | `test_rn07_*`, `test_cotacoes_defasadas_*` |
| Falha no meio da execução | Transação única | `Banco.transacao()` | `test_execucao_parcial_depois_total` |
| Validação indisponível | Indisponibilidade segura | `servicos/risco.py` | `test_erro_inesperado_aciona_suspensao_automatica` |
| Notificação não entregue | Fila com nova tentativa | `servicos/fila.py`, `notificacoes.py` | `test_esgotadas_as_tentativas_*` |
| Alteração de logs | Append-only + hash | `RN12` | `test_adulteracao_*` |
| Força bruta | MFA, bloqueio, hash | `RN10`, `RN11` | `test_rn11_*` |
| Entrada maliciosa | Validação + consultas parametrizadas (SQLAlchemy) | `api/esquemas.py` | `test_entrada_invalida_422_*` |

## 4. Requisitos não funcionais da Etapa 2

| Exigência da Etapa 2 | Atendimento |
|---|---|
| Java ou Python | Python 3.11+ (FastAPI, SQLAlchemy) |
| Domínio, regras, serviços, persistência e testes | pacotes `dominio/`, `regras/`, `servicos/`, `persistencia/`, `tests/` |
| POO: encapsulamento, abstração, herança, interfaces | `Usuario` (abstrata, 4 perfis), `Ordem` (abstrata, mercado/limitada), regras Strategy, interfaces `BolsaGateway`, `ProvedorCotacoes`, `Notificador`, `HashSenha`, `Relogio` |
| Validação de entrada e exceções seguras | `api/esquemas.py` (Pydantic) e hierarquia `SentinelTradeError` com resposta JSON sem detalhes internos |
| Separação interface / regras / persistência / integrações | `dashboard/` + `api/` · `regras/` + `servicos/` · `persistencia/` · `integracoes/` |
| Criar, consultar, alterar e cancelar ordens | CSU04–CSU08 |
| Autenticação simulada com MFA | CSU01 (código de 6 dígitos, 60 s, entregue pelo notificador simulado) |
| Saldo, posição, limite de risco, duplicidade | RN01, RN02, RN03, RN08 |
| Logs de auditoria | RN12 / CSU14 |
| Testes das regras críticas | `tests/` (157 testes; cobertura acima de 90% em `regras/`, `dominio/ordens.py` e `servicos/ordens.py`; 84% no total) |
| Banco relacional SQL | SQLite (padrão) ou PostgreSQL; DDL em `db/schema.sqlite.sql` e `db/schema.postgresql.sql` |
