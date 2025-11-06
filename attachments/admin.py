from django.contrib import admin
from .models import AttachmentIntegrationMap, AttachmentTransferLog

@admin.register(AttachmentIntegrationMap)
class AttachmentIntegrationMapAdmin(admin.ModelAdmin):
    list_display = ("origem_recebimento_id", "destino_conta_pagar_id", "numero_nf", "created_at")
    search_fields = ("origem_recebimento_id", "destino_conta_pagar_id", "numero_nf")
    list_filter = ("created_at",)

@admin.register(AttachmentTransferLog)
class AttachmentTransferLogAdmin(admin.ModelAdmin):
    list_display = ("id", "origem_id", "destino_id", "status", "tentativas", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("origem_id", "destino_id")
