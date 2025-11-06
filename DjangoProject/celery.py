import os
from celery import Celery

# Define o módulo de settings padrão do Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'DjangoProject.settings')

# Cria a aplicação Celery
app = Celery('DjangoProject')

# Carrega configurações do Django com prefixo CELERY_
app.config_from_object('django.conf:settings', namespace='CELERY')

# Descobre automaticamente tasks em apps registrados
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
