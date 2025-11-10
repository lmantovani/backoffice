# attachments/models.py

from django.db import models
from django.utils import timezone


class AttachmentIntegrationMap(models.Model):
    origem_recebimento_id = models.IntegerField(help_text="nIdReceb", db_index=True)
    destino_conta_pagar_id = models.IntegerField(
        help_text="nCodTitulo",
        db_index=True,
    )
    numero_nf = models.CharField(max_length=60, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "attachment_integration_map"
        unique_together = ("origem_recebimento_id", "destino_conta_pagar_id")
        indexes = [
            models.Index(fields=["origem_recebimento_id"]),
            models.Index(fields=["destino_conta_pagar_id"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"Map {self.origem_recebimento_id} -> {self.destino_conta_pagar_id}"


class AttachmentTransferLog(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pendente"),
        ("processing", "Processando"),
        ("success", "Sucesso"),
        ("failed", "Falhou"),
    ]

    origem_tabela = models.CharField(max_length=50, default="com-recebimento")
    origem_id = models.IntegerField(help_text="nIdReceb")

    destino_tabela = models.CharField(max_length=50, default="conta-pagar")
    destino_id = models.IntegerField(help_text="nCodTitulo")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    tentativas = models.IntegerField(default=0)
    max_tentativas = models.IntegerField(default=3)

    anexos_transferidos = models.JSONField(default=list, blank=True)
    total_anexos = models.IntegerField(default=0)
    anexos_sucesso = models.IntegerField(default=0)

    mensagem_erro = models.TextField(blank=True, null=True)
    detalhes = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    processado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "attachment_transfer_log"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["origem_id", "destino_id"]),
            models.Index(fields=["status"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"Transfer {self.origem_id} -> {self.destino_id} [{self.status}]"

    def mark_as_processing(self):
        self.status = "processing"
        self.tentativas += 1
        self.save(update_fields=["status", "tentativas", "updated_at"])

    def mark_as_success(self, anexos_info: list):
        self.status = "success"
        self.anexos_transferidos = anexos_info
        self.anexos_sucesso = len(anexos_info)
        self.processado_em = timezone.now()
        self.save(
            update_fields=[
                "status",
                "anexos_transferidos",
                "anexos_sucesso",
                "processado_em",
                "updated_at",
            ]
        )

    def mark_as_failed(self, erro: str):
        self.status = "failed"
        self.mensagem_erro = erro
        self.processado_em = timezone.now()
        self.save(
            update_fields=[
                "status",
                "mensagem_erro",
                "processado_em",
                "updated_at",
            ]
        )

    @property
    def pode_retentar(self) -> bool:
        return self.tentativas < self.max_tentativas and self.status in (
            "pending",
            "failed",
        )


class AttachmentSyncLog(models.Model):
    METODO_CHOICES = (
        ("robo", "Robô"),
        ("sistema_full_flow", "Fluxo BackOffice"),
    )

    origem_tabela = models.CharField(max_length=100)
    origem_id = models.BigIntegerField()

    destino_tabela = models.CharField(max_length=100)
    destino_id = models.BigIntegerField()

    metodo = models.CharField(max_length=30, choices=METODO_CHOICES)

    nome_arquivo = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20,
        choices=(
            ("success", "Sucesso"),
            ("failed", "Falha"),
        ),
    )
    mensagem_erro = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["origem_tabela", "origem_id"]),
            models.Index(fields=["destino_tabela", "destino_id"]),
        ]

    def __str__(self) -> str:
        return (
            f"{self.origem_tabela}:{self.origem_id} -> "
            f"{self.destino_tabela}:{self.destino_id} [{self.status}]"
        )
