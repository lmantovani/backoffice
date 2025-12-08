# BackOffice Omie – Documentação do Projeto

Este repositório contém um backoffice em Django que integra com a API do Omie ERP para automatizar fluxos de negócio, com foco inicial em:
- RF-001: Transferência de anexos entre módulos do Omie (por exemplo, de Recebimento de NF-e para Contas a Pagar).
- RF-002: Encerramento automático de Pedido de Compra quando uma NF de serviço é lançada.

A aplicação expõe endpoints via Django REST Framework (DRF), oferece páginas simples para navegação e registro de logs em banco e arquivo.

---

## Sumário
- Visão Geral e Arquitetura
- Aplicativos (apps) e responsabilidades
- Configuração do ambiente (.env)
- Como executar (servidor, Celery) – guia rápido
- Funcionalidades detalhadas
  - RF-001 – Transferência de Anexos
  - RF-002 – Encerramento de Pedido de Compra
- Endpoints (API)
- Páginas (UI)
- Modelos (tabelas) principais
- Serviços e Tarefas (services/tasks)
- Cliente Omie (omie_api.client)
- Logs e Observabilidade
- Testes (orientações)
- Solução de problemas
- Segurança e Boas práticas

---

## Visão Geral e Arquitetura

- Framework: Django 5 + Django REST Framework.
- Integração: classe OmieAPIClient centraliza chamadas HTTP para a API da Omie.
- Domínios principais:
  - attachments: transferência de anexos entre módulos do Omie.
  - purchase_orders: encerramento de pedidos de compra.
  - BackOffice: páginas simples (home e listagens) e integração de UI.
- Assíncrono: suporte opcional com Celery + Redis (tasks para processar em background).
- Persistência: suporte a PostgreSQL via DATABASE_URL; fallback para SQLite quando ausente.
- Observabilidade: logs em banco (modelos de log) e arquivo logs/django.log.

Estrutura de apps:
- omie_api: cliente HTTP + exceções e utilitários específicos do Omie.
- attachments: serviços, views e modelos para RF-001.
- purchase_orders: serviços, views e modelos para RF-002.
- BackOffice: views/templates para páginas /home, /attachments e /purchase-orders.

## Aplicativos (apps) e responsabilidades

- omie_api
  - OmieAPIClient: wrapper para endpoints Omie (listar/obter/incluir anexos, consultar/encerrar pedido de compra, etc.).
  - OmieAPIException: exceção de domínio para tratar faults da Omie.

- attachments
  - AttachmentTransferService: orquestra leitura de anexos na origem, evita duplicatas no destino e inclui anexos.
  - Views DRF (AttachmentTransferViewSet): endpoints para transferir, processar pendentes e incluir anexo.
  - Models: AttachmentTransferLog e AttachmentIntegrationMap para rastreabilidade e idempotência.
  - Tasks Celery: transferir_anexos_task (assíncrono, opcional).

- purchase_orders
  - PurchaseOrderClosureService: consulta e encerra pedidos conforme regras configuráveis.
  - Views DRF (PurchaseOrderClosureViewSet): endpoints de encerramento e reprocessamento.
  - Model: PurchaseOrderClosureLog para histórico e reprocesso.
  - Tasks Celery: encerrar_pedido_task (assíncrono, opcional).

- BackOffice
  - Views simples para páginas /home, /attachments e /purchase-orders.
  - Integra templates baseados em Bootstrap/Volt (assets em static/volt).

## Configuração do ambiente (.env)

O projeto carrega variáveis com python-decouple.

Principais chaves no arquivo .env (exemplo):
- SECRET_KEY, DEBUG, ALLOWED_HOSTS
- OMIE_APP_KEY, OMIE_APP_SECRET, OMIE_API_BASE_URL
- OMIE_PO_CLOSE_STATUS (p.ex. Encerrado ou Fechado), OMIE_PO_CLOSE_CALL, OMIE_PO_CLOSE_ENDPOINT
- DATABASE_URL (PostgreSQL) – se ausente ou vazio, o projeto usa SQLite (db.sqlite3)
- CELERY_BROKER_URL, CELERY_RESULT_BACKEND (quando usar Celery)
- Celery – controle de concorrência/estouro (opcional):
  - CELERY_WORKER_PREFETCH_MULTIPLIER (padrão 1) – evita rajadas de tasks sendo pré‑lidas.
  - CELERY_ACKS_LATE (padrão True) – melhor fairness em tasks longas.
  - RATE_LIMIT_MONITOR_TASK (padrão "6/m") – rate limit da task monitorar_pedido_e_processar.
  - RATE_LIMIT_ROBO_TASK (padrão "2/m") – rate limit do robô de sincronização.
  - RATE_LIMIT_FULL_FLOW_PENDENTES (padrão "4/m") – rate limit do processamento de pendentes do full‑flow.
  - RATE_LIMIT_TRANSFER_ANEXOS (padrão "12/m") – rate limit da task de transferência de anexos.
  - RATE_LIMIT_PROCESSAR_TRANSFERENCIAS (padrão "4/m") – rate limit da task de processar pendências de anexos.
  - RATE_LIMIT_ENCERRAR_PEDIDO (padrão "6/m") – rate limit da task de encerramento de pedido.
- Limites/Resiliência Omie e DRF (Rate Limit / Cache):
  - OMIE_MAX_RETRIES (padrão 3) – retentativas automáticas no cliente Omie para 429/5xx.
  - OMIE_RETRY_BACKOFF_SECONDS (padrão 1.0) – backoff exponencial base.
  - OMIE_RETRY_JITTER_MS (padrão 250) – jitter aleatório para evitar rajadas.
  - DRF_THROTTLE_RATE_SUPPLIERS (padrão "6/min") – limite do endpoint GET /api/suppliers/.
  - SUPPLIERS_CACHE_TTL_SECONDS (padrão 45) – TTL do cache de busca de fornecedores (em segundos).
  - SUPPLIERS_MIN_QUERY_LEN (padrão 3) – comprimento mínimo do termo para consultar a Omie (termos menores retornam lista vazia sem chamar a Omie).
  - SUPPLIERS_PER_PAGE (padrão 50) – quantidade de registros por página na chamada ListarClientes.
  - SUPPLIERS_COOLDOWN_SECONDS (padrão 5) – tempo de resfriamento local aplicado após um 429 da Omie quando o header Retry-After não estiver presente.

Atenção: não compartilhe credenciais reais em repositórios públicos. Gere e use chaves específicas para desenvolvimento.

## Como executar – Guia rápido

Para um passo-a-passo detalhado usando Windows/PowerShell, consulte SETUP.md.

Resumo:
1) Criar venv e instalar dependências: pip install -r requirements.txt
2) Ajustar .env (credenciais Omie, banco, etc.)
3) Migrar banco: python manage.py makemigrations && python manage.py migrate
4) Rodar servidor: python manage.py runserver (acessar http://127.0.0.1:8000)
5) (Opcional) Rodar Celery: celery -A DjangoProject worker -l info

## Funcionalidades detalhadas

### RF-001 – Transferência de Anexos (attachments)
Fluxo principal:
1) Listar anexos da origem no Omie (ex.: tabela "com-recebimento", campo nIdReceb).
2) Listar anexos já existentes no destino (ex.: tabela "conta_a_pagar", campo nCodTitulo) para evitar duplicatas.
3) Para cada anexo novo: obter conteúdo base64 e incluir no destino.
4) Registrar resultado em AttachmentTransferLog (contagem, duplicados, erros, tempo, etc.).

Destaques de implementação:
- Idempotência: evita incluir o mesmo arquivo novamente, comparando por nome e tamanho quando disponível.
- Logs detalhados: falhas de inclusão registram mensagens da API (faultstring) e exceções.
- Reprocesso: há endpoint para processar pendências/falhas e regra de tentativas máximas.
- Mapeamento: AttachmentIntegrationMap guarda pares origem→destino para rastrear integrações.

Uso via API:
- POST /api/attachments/transferir/ – dispara transferência síncrona ou assíncrona (Celery).
- POST /api/attachments/processar_pendentes/ – executa reprocesso de pendências/falhas.
- POST /api/attachments/incluir/ – upload base64 direto para uma tabela suportada do Omie.

### RF-002 – Encerramento de Pedido de Compra (purchase_orders)
Fluxo principal:
1) Consultar status atual do pedido no Omie.
2) Se já estiver encerrado, registrar sucesso sem ação.
3) Caso contrário, chamar a API de encerramento (parâmetros configuráveis via .env).
4) Registrar resultado em PurchaseOrderClosureLog, incluindo status anterior/novo.

Uso via API:
- POST /api/purchase-orders/encerrar/ – encerra um pedido (síncrono ou assíncrono).
- POST /api/purchase-orders/reprocessar_falhas/ – reprocessa logs com falha e tentativas remanescentes.

Configuração sensível a conta Omie:
- Algumas contas usam cStatus="Fechado", outras "Encerrado". Ajuste OMIE_PO_CLOSE_STATUS no .env, bem como call/endpoint se necessário.

## Endpoints (API)

A raiz da API: /api/

Attachments (AttachmentTransferViewSet):
- POST /api/attachments/transferir/
  - body: { origem_id, destino_id, origem_tabela?, destino_tabela?, assincrono? }
- POST /api/attachments/processar_pendentes/
- POST /api/attachments/incluir/

Purchase Orders (PurchaseOrderClosureViewSet):
- GET /api/purchase-orders/ – lista logs de encerramento (somente leitura)
- POST /api/purchase-orders/encerrar/
  - body: { numero_pedido, item_pedido?, numero_nf_servico, id_nf_servico, assincrono? }
- POST /api/purchase-orders/reprocessar_falhas/

Autenticação DRF: /api-auth/login/ (navegador). Admin Django: /admin/.

## Páginas (UI)

- /home/ – página inicial.
- /attachments/ – página simples relacionada a anexos.
- /purchase-orders/ – página simples relacionada a pedidos de compra.

## Modelos (tabelas) principais

attachments.models:
- AttachmentIntegrationMap
  - Campos: origem_recebimento_id (nIdReceb), destino_conta_pagar_id (nCodTitulo), numero_nf, created_at.
  - unique_together para evitar duplicidade de pares.
- AttachmentTransferLog
  - Rastreia transferências com status (pending, processing, success, failed), tentativas, detalhes, contagens e timestamps.
  - Propriedade pode_retentar respeita max_tentativas e status atual.

purchase_orders.models:
- PurchaseOrderClosureLog (análogo em conceito, para RF-002).

## Serviços e Tarefas

- attachments.services.AttachmentTransferService
  - transferir_anexos(origem_id, destino_id, ...)
  - processar_transferencias_pendentes()
  - registrar_mapeamento_para_transferencia(..., iniciar_transferencia, assincrono)
- attachments.tasks.transferir_anexos_task (se Celery ativo)
- purchase_orders.services.PurchaseOrderClosureService
  - encerrar_pedido_automaticamente(...)
  - reprocessar_falhas()
- purchase_orders.tasks.encerrar_pedido_task (se Celery ativo)

Signals úteis:
- attachments.signals.disparar_transferencia_por_integracao(origem_id, destino_id)
  - Pode ser chamado pela rotina que cria o título no Omie para acoplar os fluxos.

## Cliente Omie (omie_api.client)

- OmieAPIClient encapsula as chamadas com autenticação (app_key/secret) e trata erros (faultstring).
- Resiliência: retentativas automáticas em 429/5xx e falhas de rede com backoff exponencial e respeito a Retry-After.
 - Anti‑burst local: variável OMIE_MIN_INTERVAL_SECONDS (padrão 0.2s) aplica um espaçamento mínimo entre chamadas por processo (melhora quando o Celery está ativo).
  - Quando esgotadas as tentativas, a exceção OmieAPIException agora carrega status_code e retry_after (quando fornecido pelo Omie), permitindo à view propagar 429 com cabeçalho Retry-After ao cliente.
- Métodos relevantes:
  - listar_anexos(cTabela, nId)
  - obter_anexo(nIdAnexo) – retorna conteúdo base64 em cArquivo
  - incluir_anexo(tabela, n_id, nome_arquivo, arquivo_base64, descricao?)
  - consultar_pedido_compra(numero_pedido)
  - encerrar_pedido_compra(numero_pedido, codigo_item?)
- Configurações para encerramento: OMIE_PO_CLOSE_STATUS, OMIE_PO_CLOSE_CALL, OMIE_PO_CLOSE_ENDPOINT.

## Logs e Observabilidade

- Arquivo: logs/django.log (configurável em DjangoProject/settings.py).
- Banco: modelos de log (AttachmentTransferLog, PurchaseOrderClosureLog) com detalhes e métricas.
- As views/services registram eventos com logger e extras (origem/destino/log_id) para correlação.

## Testes

- Pastas tests.py em cada app para criar casos de teste (ex.: mocks do OmieAPIClient para simular respostas).
- Recomenda-se usar pytest e requests-mock ou responses para cobrir fluxos sem bater na API real.

## Solução de problemas (FAQ)

- Credenciais Omie inválidas: confirme OMIE_APP_KEY/OMIE_APP_SECRET no .env.
- Diferenças de status "Encerrado" vs "Fechado": ajuste OMIE_PO_CLOSE_STATUS.
- Erro de conexão PostgreSQL: remova/ajuste DATABASE_URL para usar SQLite no dev.
- Celery não processa: suba Redis e configure CELERY_BROKER_URL/RESULT_BACKEND.
- Fuso horário/ZoneInfo no Windows: instale tzdata (já em requirements.txt).
- 429 Too Many Requests na Omie ao buscar fornecedores: o endpoint /api/suppliers/ aplica throttling (DRF_THROTTLE_RATE_SUPPLIERS) e cache curto (SUPPLIERS_CACHE_TTL_SECONDS). Ajuste as variáveis conforme a necessidade. O cliente Omie também re-tenta automaticamente.
 - Muitas requisições quando o Celery está rodando: ajuste os limites em settings (.env) – OMIE_MIN_INTERVAL_SECONDS para espaçar chamadas no cliente; defina RATE_LIMIT_* para tasks críticas e mantenha CELERY_WORKER_PREFETCH_MULTIPLIER=1. Isso reduz picos e evita 429 no backend da Omie.
  - Além disso, o backend evita consultas à Omie para termos muito curtos (SUPPLIERS_MIN_QUERY_LEN) e ativa um cooldown local após receber 429 (SUPPLIERS_COOLDOWN_SECONDS ou Retry-After informado pelo Omie). Durante o cooldown, retornará 429 imediatamente com cabeçalho Retry-After quando possível.

## Segurança e Boas práticas

- Trate as variáveis do .env como segredos; evite comitar chaves reais.
- Use usuários e permissões mínimos no Omie para as operações necessárias.
- Adicione validações extras nas views se expor os endpoints publicamente (auth/permissões no DRF).

---

Referências rápidas:
- Guia de execução detalhado: SETUP.md
- URLs principais: DjangoProject/urls.py
- Serviços: attachments/services.py, purchase_orders/services.py
- Cliente Omie: omie_api/client.py
