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
