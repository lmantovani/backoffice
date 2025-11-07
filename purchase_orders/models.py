from django.db import models
from django.utils import timezone


class PurchaseOrderClosureLog(models.Model):
    """
    Log de encerramento automático de pedidos de compra (RF-002)
    """
    STATUS_CHOICES = [
        ('pending', 'Pendente'),
        ('processing', 'Processando'),
        ('success', 'Sucesso'),
        ('failed', 'Falhou'),
    ]

    # Dados do Pedido de Compra
    numero_pedido = models.CharField(max_length=50)
    item_pedido = models.CharField(max_length=50, blank=True, null=True)

    # Dados da Nota Fiscal de Serviço
    numero_nf_servico = models.CharField(max_length=50)
    id_nf_servico = models.IntegerField(help_text='ID da NF de serviço no Omie')

    # Status e controle
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    tentativas = models.IntegerField(default=0)
    max_tentativas = models.IntegerField(default=3)

    # Mensagens e erros
    mensagem_erro = models.TextField(blank=True, null=True)
    detalhes = models.JSONField(default=dict, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    processado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'purchase_order_closure_log'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['numero_pedido']),
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Closure PC {self.numero_pedido} [{self.status}]"

    def mark_as_processing(self):
        """Marca como em processamento"""
        self.status = 'processing'
        self.tentativas += 1
        self.save(update_fields=['status', 'tentativas', 'updated_at'])

    def mark_as_success(self, detalhes: dict = None):
        """Marca como sucesso"""
        self.status = 'success'
        if detalhes:
            self.detalhes = detalhes
        self.processado_em = timezone.now()
        self.save(update_fields=['status', 'detalhes', 'processado_em', 'updated_at'])

    def mark_as_failed(self, erro: str):
        """Marca como falha"""
        self.status = 'failed'
        self.mensagem_erro = erro
        self.processado_em = timezone.now()
        self.save(update_fields=['status', 'mensagem_erro', 'processado_em', 'updated_at'])

    @property
    def pode_retentar(self):
        """Verifica se ainda pode retentar"""
        return self.tentativas < self.max_tentativas and self.status in ['pending', 'failed']

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
        return f"{self.origem_tabela}:{self.origem_id} -> {self.destino_tabela}:{self.destino_id} [{self.status}]"