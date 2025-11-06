from django.apps import AppConfig


class AttachmentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'attachments'
    verbose_name = 'Gestão de Anexos'

    def ready(self):
        # Importa os signals quando a app estiver pronta
        try:
            import attachments.signals
        except ImportError:
            pass
