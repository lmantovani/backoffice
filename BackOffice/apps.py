from django.apps import AppConfig


class BackofficeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'BackOffice'

    def ready(self):
        # Personalização segura do Django Admin após o carregamento dos apps
        from django.utils.translation import gettext_lazy as _
        from django.contrib import admin
        admin.site.site_header = _("BackOffice - Administração")
        admin.site.site_title = _("BackOffice Admin")
        admin.site.index_title = _("Bem-vindo ao painel de administração")
