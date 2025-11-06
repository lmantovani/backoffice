from django.db import models
from django.utils import timezone


class AttachmentIntegrationMap(models.Model):
    """
    Log/Mapa mínimo para rastrear a origem (nIdReceb) e o destino (nCodTitulo) do CP criado via integração.
    Atende RF-001: permite recuperar o origem_id para futura transferência de anexos.
    """
    origem_recebimento_id = models.IntegerField(help_text='nIdReceb', db_index=True)
    destino_conta_pagar_id = models.IntegerField(help_text='nCodTitulo', db_index=True)
    numero_nf = models.CharField(max_length=60, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'attachment_integration_map'
        unique_together = ('origem_recebimento_id', 'destino_conta_pagar_id')
        indexes = [
            models.Index(fields=['origem_recebimento_id']),
            models.Index(fields=['destino_conta_pagar_id']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Map {self.origem_recebimento_id} -> {self.destino_conta_pagar_id}"


class AttachmentTransferLog(models.Model):
    """
    Log de transferências de anexos entre módulos (RF-001)
    """
    STATUS_CHOICES = [
        ('pending', 'Pendente'),
        ('processing', 'Processando'),
        ('success', 'Sucesso'),
        ('failed', 'Falhou'),
    ]

    # Origem (Recebimento de NF-e)
    origem_tabela = models.CharField(max_length=50, default='com-recebimento')
    origem_id = models.IntegerField(help_text='nIdReceb')

    # Destino (Contas a Pagar)
    destino_tabela = models.CharField(max_length=50, default='conta_a_pagar')
    destino_id = models.IntegerField(help_text='nCodTitulo')

    # Status e controle
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    tentativas = models.IntegerField(default=0)
    max_tentativas = models.IntegerField(default=3)

    # Anexos transferidos
    anexos_transferidos = models.JSONField(default=list, blank=True)
    total_anexos = models.IntegerField(default=0)
    anexos_sucesso = models.IntegerField(default=0)

    # Mensagens e erros
    mensagem_erro = models.TextField(blank=True, null=True)
    detalhes = models.JSONField(default=dict, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    processado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'attachment_transfer_log'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['origem_id', 'destino_id']),
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Transfer {self.origem_id} -> {self.destino_id} [{self.status}]"

    def mark_as_processing(self):
        """Marca como em processamento"""
        self.status = 'processing'
        self.tentativas += 1
        self.save(update_fields=['status', 'tentativas', 'updated_at'])

    def mark_as_success(self, anexos_info: list):
        """Marca como sucesso"""
        self.status = 'success'
        self.anexos_transferidos = anexos_info
        self.anexos_sucesso = len(anexos_info)
        self.processado_em = timezone.now()
        self.save(update_fields=['status', 'anexos_transferidos', 'anexos_sucesso',
                                 'processado_em', 'updated_at'])

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