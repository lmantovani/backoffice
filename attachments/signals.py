import logging

logger = logging.getLogger(__name__)

"""
Observação importante sobre disparo automático de transferência de anexos
-------------------------------------------------------------------------

Antes: este módulo registrava um receiver de post_save com sender="seu_app.ContasPagar",
que é um placeholder e quebra o carregamento do Django porque o modelo não existe.

Agora: removemos o receiver inválido. Existem duas formas recomendadas de disparar a
transferência:

1) Chamada explícita a partir da integração que cria o Contas a Pagar no Omie:
   from attachments.services import AttachmentTransferService
   AttachmentTransferService().transferir_anexos(origem_id, destino_id)

2) Webhook/retorno do Omie (quando disponível), chamando o mesmo serviço acima.

Se, no futuro, você tiver um modelo Django real que represente Contas a Pagar,
você pode restaurar um signal apontando para esse modelo real.
"""


def disparar_transferencia_por_integracao(origem_id: int, destino_id: int):
    """Utilitário para ser chamado pela integração após criar o título no Omie."""
    from .services import AttachmentTransferService

    logger.info(
        f"Disparo explícito de transferência de anexos (origem={origem_id} -> destino={destino_id})"
    )
    service = AttachmentTransferService()
    return service.transferir_anexos(origem_id=origem_id, destino_id=destino_id)