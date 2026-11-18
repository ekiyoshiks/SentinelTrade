# SentinelTrade

Plataforma **simulada** de negociação de ativos da **Orion Capital**, projetada para alta criticidade (disponibilidade, integridade, auditabilidade e tolerância a falhas). Projeto da disciplina *Projeto de Software* (Mackenzie). Nenhuma integração é real: Bolsa, provedor de cotações e serviço de notificação são simuladores, com injeção de falhas.

## Estrutura do repositório

| Caminho | Conteúdo |
|---|---|
| `docs/01-requisitos.md` … `docs/03-visao-sistemica.md` | **Fase 1** — requisitos, casos de uso, visão sistêmica (já versionados) |
| `docs/04-criterios-de-aceitacao.md` | Critérios de aceitação (Dado/Quando/Então) ligados aos testes |
| `docs/05-rastreabilidade.md` | Matriz requisito → caso de uso → regra → código → teste |
| `docs/diagramas/casos-de-uso.puml` (+ `.svg`) | UML de Casos de Uso — fonte PlantUML versionada |
| `src/sentineltrade/` | **Fase 2** — código (Python) |
| `db/` | DDL SQL (`schema.sqlite.sql`, `schema.postgresql.sql`) |
| `tests/` | Testes automatizados (`pytest`) |

## Arquitetura (Etapa 2)

```
dashboard/ (HTML+JS)  →  api/ (FastAPI)  →  servicos/  →  regras/ + dominio/
                                              │              
                                              ├→ persistencia/ (SQLAlchemy → SQLite/PostgreSQL)
                                              └→ integracoes/ (interfaces + simuladores: Bolsa, cotações, notificação)
```

- **dominio/**: `Usuario` (abstrata; Investidor, Operador de Risco, Administrador, Auditor), `Ordem` (abstrata; a mercado e limitada), `Conta`, `Posicao`, máquina de estados da ordem. Atributos encapsulados.
- **regras/**: uma classe por regra de negócio (RN01–RN13, padrão Strategy), encadeadas em `ValidadorOrdem`.
- **servicos/**: casos de uso (ordens, autenticação/MFA, risco, retorno da Bolsa, reprocessamento, auditoria, notificações, cadastros, consultas).
- **persistencia/**: mapeamento imperativo (o domínio não conhece o banco), repositórios, transações, gatilhos que tornam a auditoria *append-only*.
- **integracoes/**: interfaces `BolsaGateway`, `ProvedorCotacoes`, `Notificador` e implementações simuladas.
- **Resiliência**: idempotência de ordens e de retornos da Bolsa, fila durável no banco com nova tentativa, reprocessamento (consulta a Bolsa antes de reenviar), intervenção manual e **indisponibilidade segura** (manual ou automática).
- **Segurança**: senha com Argon2, MFA simulado (código de 6 dígitos, 60 s), bloqueio após 5 falhas, sessão por cookie assinado (HttpOnly, SameSite=Strict), autorização por perfil no servidor, erros sem detalhes internos, auditoria com hash encadeado.

## Como executar

Requer Python 3.11+.

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                   # opcional

export PYTHONPATH=src                                  # Windows (PowerShell): $env:PYTHONPATH="src"
python -m sentineltrade.cli init-db --seed             # cria o banco e dados de demonstração
python -m sentineltrade.cli run                        # http://127.0.0.1:8000
```

Abra **http://127.0.0.1:8000**. Usuários de demonstração (senha `Orion@Demo2026`, ou o valor de `SEED_SENHA`):

| Usuário | Perfil | O que ver |
|---|---|---|
| `ana`, `bruno`, `carla` | Investidor | cotações, enviar/alterar/cancelar ordens, carteira, notificações |
| `operador` | Operador de Risco | painel, limites, indisponibilidade segura, **simulação de falhas** |
| `admin` | Administrador | investidores/contas, ativos, perfis de acesso |
| `auditor` | Auditor | registros de auditoria e verificação de integridade |

O **segundo fator** aparece na tela de login, num quadro "celular simulado" (o código também é entregue pelo notificador simulado). O quadro existe só com `MODO_SIMULACAO=true`.

### Banco de dados

SQLite por padrão (`data/local/sentineltrade.db`). Para PostgreSQL: `pip install "psycopg[binary]"` e `DATABASE_URL=postgresql+psycopg://usuario:senha@host:5432/sentineltrade`. O DDL equivalente está em `db/`; para regerá-lo: `python -m sentineltrade.cli export-schema --dialeto sqlite|postgresql`.

### Testes

```bash
pytest                                  # 157 testes
pytest --cov=sentineltrade              # cobertura
```

Cobrem validação de entrada, regras RN01–RN13, **todas as transições de estado** (permitidas e proibidas), idempotência, retorno duplicado da Bolsa, time-out e reprocessamento, indisponibilidade segura, MFA/bloqueio, perfis, API HTTP e a detecção de adulteração da auditoria.

## Roteiro de demonstração das falhas (perfil `operador`, aba "Simulação de falhas")

1. **Bolsa sem resposta** → como `ana`, envie uma ordem: ela vai para *Falha*; volte a "Normal" e execute o ciclo: a ordem é concluída **sem duplicar**.
2. **Resposta perdida** → a Bolsa recebe a ordem, mas a confirmação se perde; o reprocessamento consulta antes de reenviar.
3. **Retorno duplicado / execução parcial / rejeição** → "armar" na simulação e observar saldo e histórico da ordem.
4. **Provedor de cotações fora do ar** → cotações ficam *defasadas* e ordens a mercado são recusadas (RN07).
5. **Indisponibilidade segura** → novas ordens recusadas; consultas e cancelamentos continuam.
6. **Auditoria** → como `auditor`, "Verificar integridade".

## Configuração

Variáveis em `.env` (ver `.env.example`): `DATABASE_URL`, `JWT_SECRET` (sem ela, uma chave aleatória é gerada a cada execução), `SEED_SENHA`, `MODO_SIMULACAO`, `MFA_*`, `BOLSA_TIMEOUT_MS`, `BOLSA_MAX_TENTATIVAS`, `COTACAO_MAX_IDADE_S` etc.

## Limitações conhecidas

- Processo único: as escritas são serializadas por um bloqueio em memória (suficiente para o escopo acadêmico; para várias instâncias seria necessário bloqueio no banco).
- Tudo que é "externo" é simulado; o código de MFA não é enviado a um provedor real.
- O dashboard consulta a API a cada 2 s (sem WebSocket).
