# 04 — Critérios de aceitação

Critérios no formato **Dado / Quando / Então** para os casos de uso de descrição expandida (CSU01, CSU04, CSU05, CSU06, CSU13, CSU14, CSU16 e CSU18). Cada critério aponta para o teste automatizado que o verifica (`tests/`, executar com `pytest`). A relação completa entre requisitos, casos de uso, regras, código e testes está em [05-rastreabilidade.md](05-rastreabilidade.md).

Convenção de identificadores: `CA-<caso de uso>-<n>`. Os testes citados ficam no arquivo indicado na coluna **Verificado por**.

## CSU01 — Autenticar com MFA (RF-01 · RN10, RN11)

| ID | Critério | Verificado por |
|---|---|---|
| CA-01-1 | **Dado** um usuário ativo, **quando** informa credenciais válidas e o código de uso único correto dentro de 60 s, **então** o sistema concede sessão com as permissões do seu perfil. | `test_autenticacao_cadastros_auditoria.py::test_login_exige_segundo_fator` |
| CA-01-2 | **Dado** credenciais inválidas (usuário inexistente ou senha errada), **quando** o usuário tenta entrar, **então** a mensagem é a mesma nos dois casos ("Credenciais inválidas") e não revela qual dado falhou. | `::test_senha_incorreta_mensagem_generica` |
| CA-01-3 | **Dado** um código MFA expirado, **quando** o usuário o informa, **então** o sistema recusa com `MFA_EXPIRADO` e permite emitir novo código. | `::test_codigo_mfa_invalido_e_expirado` |
| CA-01-4 | **Dado** um código MFA já utilizado, **quando** é reapresentado, **então** é recusado. | `::test_codigo_mfa_nao_pode_ser_reutilizado` |
| CA-01-5 | **Dado** 5 tentativas inválidas (RN11), **quando** o usuário tenta novamente — mesmo com a senha correta —, **então** a conta está bloqueada; **e** após 15 minutos volta a funcionar. | `::test_rn11_bloqueio_apos_tentativas_e_desbloqueio_por_tempo` |
| CA-01-6 | **Dado** uma senha com menos de 12 caracteres ou sem letras e números (RN10), **quando** é cadastrada, **então** é rejeitada; **e** a senha é armazenada somente como hash Argon2. | `::test_rn10_politica_de_senha`, `::test_senha_armazenada_como_hash_argon2` |
| CA-01-7 | **Dado** um token de sessão adulterado ou expirado, **quando** usado, **então** o acesso é negado. | `::test_token_adulterado_e_rejeitado`, `::test_token_expira` |
| CA-01-8 | **Dado** qualquer tentativa de login (sucesso ou falha), **então** ela fica registrada na auditoria sem gravar senha nem código. | `::test_eventos_relevantes_sao_auditados`, `::test_auditoria_nao_registra_senha_nem_codigo_mfa` |

## CSU04 — Enviar Ordem (RF-08, RF-09, RF-12, RF-20 · RN01–RN08, RN13)

| ID | Critério | Verificado por |
|---|---|---|
| CA-04-1 | **Dado** saldo suficiente e cotação atual, **quando** o investidor envia uma compra a mercado, **então** a ordem é validada, enviada à Bolsa e, ao executar, o saldo é debitado e a posição creditada. | `test_ordens_regras.py::test_compra_a_mercado_executa_e_debita_saldo` |
| CA-04-2 | **Dado** saldo insuficiente (RN01), **quando** envia a ordem, **então** ela fica **Rejeitada**, com o motivo, e nada permanece reservado. | `::test_rn01_saldo_insuficiente_rejeita_e_persiste` |
| CA-04-3 | **Dado** posição insuficiente (RN02), **quando** envia uma venda, **então** a ordem é rejeitada; **e** uma venda válida reserva a quantidade e a libera se a ordem for cancelada. | `::test_rn02_venda_sem_posicao_rejeitada`, `::test_rn02_venda_reserva_posicao_e_libera_no_cancelamento` |
| CA-04-4 | **Dado** limite por ordem ou diário excedido (RN03), **quando** envia, **então** a ordem é rejeitada informando o limite. | `::test_rn03_limite_por_ordem`, `::test_rn03_limite_diario` |
| CA-04-5 | **Dado** mercado fechado ou ativo suspenso (RN04), **quando** envia, **então** a ordem é rejeitada. | `::test_rn04_mercado_fechado_rejeita`, `test_autenticacao_cadastros_auditoria.py::test_ativo_suspenso_nao_aceita_ordens` |
| CA-04-6 | **Dado** quantidade que não é múltipla do lote (RN05), **quando** envia, **então** o sistema informa o erro e **não cria ordem**. | `::test_rn05_quantidade_fora_do_lote_nao_cria_ordem` |
| CA-04-7 | **Dado** ordem limitada com preço inválido ou fora da faixa de ±10% (RN06), **quando** envia, **então** é recusada sem criar ordem. | `::test_rn06_preco_limitada_fora_da_faixa`, `::test_rn06_preco_zero_ou_negativo`, `::test_limitada_sem_preco_e_invalida` |
| CA-04-8 | **Dado** cotação com mais de 5 s (RN07), **quando** envia ordem a mercado, **então** é recusada e o sistema sugere ordem limitada. | `::test_rn07_cotacao_defasada_bloqueia_ordem_a_mercado` |
| CA-04-9 | **Dado** a mesma chave de idempotência (RN08), **quando** a ordem é enviada duas vezes, **então** existe uma única ordem e a segunda resposta devolve a original (HTTP 200, `duplicada=true`). | `::test_rn08_mesma_chave_nao_duplica`, `test_api.py::test_criar_ordem_201_e_duplicada_200` |
| CA-04-10 | **Dado** o modo de indisponibilidade segura ativo, **quando** envia, **então** a ordem é recusada (HTTP 503) com mensagem clara. | `test_integracao_bolsa.py::test_suspensao_manual_bloqueia_novas_ordens_mas_permite_consultar_e_cancelar`, `test_api.py::test_suspensao_devolve_503_e_aparece_em_saude` |
| CA-04-11 | **Dado** a Bolsa sem resposta, **quando** a ordem é enviada, **então** ela vai para **Falha**, a reserva é mantida e a ordem segue para reprocessamento (CSU18). | `test_integracao_bolsa.py::test_bolsa_sem_resposta_marca_falha_e_reprocessa_ao_voltar` |
| CA-04-12 | **Dado** que a resposta da Bolsa se perdeu, **quando** o sistema reprocessa, **então** a ordem é executada **uma única vez** (consulta antes de reenviar). | `::test_resposta_perdida_nao_gera_ordem_duplicada_na_bolsa` |
| CA-04-13 | **Dado** um investidor, **quando** consulta ou cancela ordem de outro investidor (RN13), **então** o acesso é negado. | `test_ordens_regras.py::test_nao_ve_nem_altera_ordem_de_outro_investidor`, `test_api.py::test_investidor_nao_le_ordem_de_outro` |
| CA-04-14 | **Dado** entrada inválida (tipo, lado, ativo inexistente, quantidade negativa), **quando** enviada, **então** é rejeitada sem vazar detalhes internos. | `::test_entradas_invalidas`, `test_api.py::test_entrada_invalida_422_sem_vazar_detalhes_internos` |

## CSU05 — Alterar Ordem (RF-11 · RN01–RN07, RN09)

| ID | Critério | Verificado por |
|---|---|---|
| CA-05-1 | **Dado** ordem em estado alterável (RN09), **quando** o investidor altera a quantidade, **então** a ordem é revalidada, a reserva é recalculada e a Bolsa é informada. | `test_ordens_regras.py::test_alterar_ordem_aberta_recalcula_reserva` |
| CA-05-2 | **Dado** ordem Executada, Cancelada ou Rejeitada, **quando** se tenta alterar, **então** o sistema recusa. | `::test_rn09_nao_altera_nem_cancela_ordem_encerrada` |
| CA-05-3 | **Dado** cada transição de estado, **então** ela é registrada no histórico da ordem. | `::test_historico_registra_cada_transicao` |

## CSU06 — Cancelar Ordem (RF-10 · RN09, RN13)

| ID | Critério | Verificado por |
|---|---|---|
| CA-06-1 | **Dado** ordem ativa, **quando** o investidor confirma o cancelamento, **então** o estado vira **Cancelada** e o saldo/quantidade reservados são liberados. | `test_ordens_regras.py::test_cancelar_libera_reserva_e_vai_para_cancelada` |
| CA-06-2 | **Dado** execução durante o cancelamento, **então** o resultado da execução prevalece e saldo e posição permanecem consistentes. | `test_integracao_bolsa.py::test_cancelamento_concorrente_com_execucao_e_consistente` |
| CA-06-3 | **Dado** ordem encerrada, **quando** se tenta cancelar, **então** o sistema recusa. | `test_ordens_regras.py::test_rn09_nao_altera_nem_cancela_ordem_encerrada` |

## CSU13 — Acionar Indisponibilidade Segura (RF-19)

| ID | Critério | Verificado por |
|---|---|---|
| CA-13-1 | **Dado** a suspensão acionada pelo Operador de Risco, **então** novas ordens são recusadas, mas consultas e cancelamentos continuam disponíveis; **e** ao encerrar a suspensão as ordens voltam a ser aceitas. | `test_integracao_bolsa.py::test_suspensao_manual_bloqueia_novas_ordens_mas_permite_consultar_e_cancelar` |
| CA-13-2 | **Dado** suspensão limitada a um ativo, **então** os demais ativos continuam negociáveis. | `::test_suspensao_por_ativo_nao_afeta_outros` |
| CA-13-3 | **Dado** falha inesperada na validação, **então** o sistema ativa a suspensão sozinho (falha segura). | `::test_erro_inesperado_aciona_suspensao_automatica` |
| CA-13-4 | **Dado** um perfil sem permissão (investidor), **quando** tenta acionar a suspensão, **então** recebe acesso negado (HTTP 403). | `test_autenticacao_cadastros_auditoria.py::test_investidor_nao_acessa_funcoes_administrativas`, `test_api.py::test_perfil_sem_permissao_recebe_403` |

## CSU14 — Consultar Registros de Auditoria (RF-17 · RN12)

| ID | Critério | Verificado por |
|---|---|---|
| CA-14-1 | **Dado** eventos relevantes (login, ordens, suspensões), **então** estão registrados e consultáveis pelo Auditor. | `test_autenticacao_cadastros_auditoria.py::test_eventos_relevantes_sao_auditados` |
| CA-14-2 | **Dado** a verificação de integridade, **então** o sistema informa que a cadeia de hash está íntegra; **e** a própria consulta é auditada. | `::test_cadeia_de_hash_integra_e_consulta_e_auditada` |
| CA-14-3 | **Dado** tentativa de alterar ou apagar registro, **então** o banco recusa (append-only). | `::test_auditoria_e_append_only_no_banco` |
| CA-14-4 | **Dado** um registro adulterado por quem contornou o banco, **então** a verificação detecta o registro suspeito. | `::test_adulteracao_e_detectada_pela_cadeia_de_hash` |

## CSU16 — Processar Retorno da Bolsa (RF-12, RF-13, RF-14 · RN08, RN09)

| ID | Critério | Verificado por |
|---|---|---|
| CA-16-1 | **Dado** retorno de execução parcial seguido de total, **então** os estados passam por Parcialmente Executada e Executada e a quantidade final é a da ordem. | `test_integracao_bolsa.py::test_execucao_parcial_depois_total` |
| CA-16-2 | **Dado** rejeição pela Bolsa, **então** a ordem fica Rejeitada e a reserva é liberada. | `::test_bolsa_rejeita_ordem_libera_reserva` |
| CA-16-3 | **Dado** o mesmo retorno entregue duas vezes, **então** saldo e posição são atualizados **uma única vez**. | `::test_retorno_duplicado_da_bolsa_e_processado_uma_unica_vez` |

## CSU18 — Reprocessar Ordens Pendentes (RF-21 · RN08)

| ID | Critério | Verificado por |
|---|---|---|
| CA-18-1 | **Dado** ordem em Falha e a Bolsa de volta, **então** o reprocessamento consulta a Bolsa e conclui a ordem sem duplicá-la. | `test_integracao_bolsa.py::test_bolsa_sem_resposta_marca_falha_e_reprocessa_ao_voltar` |
| CA-18-2 | **Dado** o limite de tentativas esgotado, **então** a ordem vai para **Intervenção Manual** e o investidor é notificado. | `::test_esgotadas_as_tentativas_vai_para_intervencao_manual_e_notifica` |

## Máquina de estados (transversal)

| ID | Critério | Verificado por |
|---|---|---|
| CA-EST-1 | A tabela de transições implementada é **idêntica** à do diagrama de estados da Fase 1. | `test_estados.py::test_tabela_de_transicoes_corresponde_ao_diagrama_da_fase_1` |
| CA-EST-2 | Toda transição permitida é aceita e **toda transição não permitida** levanta `TransicaoInvalidaError` (as 81 combinações de estado origem x destino: 13 permitidas e 68 proibidas). | `test_estados.py::test_transicao_permitida`, `::test_transicao_proibida_levanta_excecao` |
| CA-EST-3 | Estados finais não têm saída; os estados alteráveis são Validada, Enviada e Parcialmente Executada (RN09). | `::test_estados_finais_nao_tem_saida`, `::test_estados_alteraveis_rn09` |
