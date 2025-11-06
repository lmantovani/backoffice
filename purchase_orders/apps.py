from django.apps import AppConfig


class PurchaseOrdersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'purchase_orders'
    verbose_name = 'Pedidos de Compra'

    def ready(self):
        # Importa os signals quando a app estiver pronta
        try:
            import purchase_orders.signals
        except ImportError:
            pass
