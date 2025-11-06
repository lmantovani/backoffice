from celery import shared_task
import logging
from .services import AttachmentTransferService

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def transferir_anexos_task(self, origem_id: int, destino_id: int):
    """
    Task assíncrona para transferir anexos
    """
    try:
        logger.info(f"Iniciando transferência assíncrona: {origem_id} -> {destino_id}")
        service = AttachmentTransferService()
        resultado = service.transferir_anexos(origem_id, destino_id)

        return {
            'status': resultado.status,
            'anexos_transferidos': resultado.anexos_sucesso,
            'total_anexos': resultado.total_anexos
        }
    except Exception as exc:
        logger.error(f"Erro na task de transferência: {str(exc)}")
        raise self.retry(exc=exc, countdown=60)


@shared_task
def processar_transferencias_pendentes_task():
    """
    Task periódica para processar transferências pendentes
    Agendar para rodar a cada 5 minutos, por exemplo
    """
    logger.info("Processando transferências pendentes...")
    service = AttachmentTransferService()
    resultados = service.processar_transferencias_pendentes()

    return {
        'total_processados': len(resultados),
        'sucessos': len([r for r in resultados if r.status == 'success']),
        'falhas': len([r for r in resultados if r.status == 'failed'])
    }