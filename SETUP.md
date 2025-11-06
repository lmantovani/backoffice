# Guia de execução do projeto (Windows/PowerShell)

Este guia descreve como preparar o ambiente, criar/aplicar migrations, rodar o servidor Django e (opcionalmente) o Celery para testar o RF‑001.

## 1) Pré‑requisitos
- Python 3.11+
- PowerShell
- (Opcional) PostgreSQL 14+ se desejar usar o DATABASE_URL do .env
- (Opcional) Redis 6+ para tarefas assíncronas com Celery

## 2) Clonar o projeto e entrar na pasta
```powershell
cd C:\Users\LeandroMantovani\PycharmProjects\DjangoProject
```

## 3) Criar e ativar o ambiente virtual
```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

## 4) Instalar dependências
```powershell
pip install -r requirements.txt
```

## 5) Configurar variáveis de ambiente
O arquivo `.env` já existe no repositório.

- Para usar SQLite (sem precisar de PostgreSQL), comente/remova a linha DATABASE_URL do `.env` ou defina `DATABASE_URL=` (vazio). O projeto cairá no fallback de SQLite (db.sqlite3). 
- Para usar PostgreSQL, mantenha e ajuste `DATABASE_URL` conforme seu ambiente.
- Preencha `OMIE_APP_KEY` e `OMIE_APP_SECRET` com suas credenciais reais da Omie para testes reais contra a API.

## 6) Criar migrations e aplicar
Gere as migrations para os apps com modelos e aplique no banco.
```powershell
# Gerar migrations
python manage.py makemigrations attachments purchase_orders BackOffice

# Aplicar migrations
python manage.py migrate
```

Dica: se estiver usando PostgreSQL e ainda não criou o banco/usuário, crie antes ou troque para SQLite conforme item 5.

## 7) Criar superusuário (opcional, para acessar /admin)
```powershell
python manage.py createsuperuser
```

## 8) Rodar o servidor Django
```powershell
python manage.py runserver
```
Acesse:
- Admin: http://127.0.0.1:8000/admin/
- API router: http://127.0.0.1:8000/api/

## 9) (Opcional) Rodar Celery para tarefas assíncronas
Se quiser usar a fila assíncrona (ex.: `transferir_anexos_task`), suba um broker (ex.: Redis) e configure as variáveis no `.env`:
```
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
```
Então, em dois terminais separados (com venv ativo):
```powershell
# Worker
celery -A DjangoProject worker -l info

# (Opcional) Beat para agendar tasks periódicas
celery -A DjangoProject beat -l info
```

## 10) Testar os endpoints do RF‑001
- Síncrono (resposta imediata):
```powershell
curl -X POST http://127.0.0.1:8000/api/attachments/transferir/ ^
  -H "Content-Type: application/json" ^
  -d "{\"origem_id\": 12345, \"destino_id\": 67890, \"assincrono\": false}"
```

- Assíncrono (via Celery):
```powershell
curl -X POST http://127.0.0.1:8000/api/attachments/transferir/ ^
  -H "Content-Type: application/json" ^
  -d "{\"origem_id\": 12345, \"destino_id\": 67890, \"assincrono\": true}"
```

- Processar pendentes:
```powershell
curl -X POST http://127.0.0.1:8000/api/attachments/processar_pendentes/
```

Observações:
- Os IDs `origem_id` (nIdReceb) e `destino_id` (nCodTitulo) devem existir na sua conta Omie para testes reais. Caso contrário, use mocks ou valide apenas o fluxo até o retorno de erro da API.
- Logs ficam em `logs/django.log` (ajuste o logging conforme desejar). Também é possível inspecionar os registros no admin para os modelos `AttachmentTransferLog` e `AttachmentIntegrationMap`.

## 11) Problemas comuns
- Erro de conexão com PostgreSQL: remova/ajuste `DATABASE_URL` para usar SQLite.
- Celery não inicia: instale e rode Redis ou ajuste o broker/backend para outro serviço de sua preferência.
- Credenciais Omie inválidas: atualize `OMIE_APP_KEY`/`OMIE_APP_SECRET` no `.env`.
- Erro ao iniciar o Django no Windows relacionado a fuso horário (TIME_ZONE/ZoneInfo): instale o pacote `tzdata` (agora incluído em requirements.txt). Após `pip install -r requirements.txt`, tente novamente `python manage.py runserver`.

## 12) Próximos passos (opcionais)
- Adicionar testes automatizados para os serviços de anexos usando mocks do cliente Omie.
- Configurar pipelines (pre-commit/CI) para validar lint e testes.

# Como criar as telas (Admin) e primeiro login no Django

Estas instruções ajudam a preparar o ambiente, criar o usuário administrador e acessar as telas do sistema (Admin) e a API navegável do DRF.

## 1) Instalar dependências
```bash
pip install -r requirements.txt
```

## 2) Configurar variáveis de ambiente
Edite o arquivo `.env` na raiz do projeto se necessário (SECRET_KEY, DEBUG, DATABASE_URL, etc.). Por padrão, sem `DATABASE_URL`, o projeto usa SQLite.

## 3) Aplicar migrações (criar tabelas)
```bash
python manage.py migrate
```

## 4) Criar superusuário (primeiro login)
```bash
python manage.py createsuperuser
```
Siga as perguntas no terminal para definir usuário e senha.

## 5) Executar o servidor
```bash
python manage.py runserver
```

## 6) Acessar as telas
- Página inicial: http://127.0.0.1:8000/home/
- Admin (telas de administração): http://127.0.0.1:8000/admin/
  - Faça login com o superusuário criado no passo 4.
- API do DRF: http://127.0.0.1:8000/api/
- Login do DRF (para testar endpoints protegidos no navegador): http://127.0.0.1:8000/api-auth/login/

## 7) O que aparece no Admin
- Logs de Transferência de Anexos
- Mapas de Integração de Anexos
- Logs de Encerramento de Pedidos de Compra

Esses modelos já estão registrados no Admin e prontos para uso.

## Dicas
- Para alterar o banco para PostgreSQL, configure `DATABASE_URL` no `.env` como no exemplo.
- O título e cabeçalho do Admin foram personalizados em `DjangoProject/settings.py`.
