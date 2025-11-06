from django.contrib import admin
from .models import PurchaseOrderClosureLog

@admin.register(PurchaseOrderClosureLog)
class PurchaseOrderClosureLogAdmin(admin.ModelAdmin):
    list_display = ("id", "numero_pedido", "item_pedido", "status", "tentativas", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("numero_pedido", "item_pedido", "numero_nf_servico", "id_nf_servico")
