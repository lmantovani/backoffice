from celery import shared_task
import logging
from .services import PurchaseOrderClosureService
from celery import shared_task

from .services import PurchaseOrderRobotService, FullFlowPurchaseOrderService
from .models import PurchaseOrderIntegration

logger = logging.getLogger(__name__)


@shared_task
def robo_sincronizar_pedidos():
    service = PurchaseOrderRobotService()
    service.processar()
    logger.info("Robô de sincronização de pedidos executado com sucesso.")


@shared_task
def full_flow_processar_pedidos_pendentes():
    """
    Procura pedidos criados pelo BackOffice que ainda não geraram financeiro
    e tenta processar.
    """
    service = FullFlowPurchaseOrderService()
    pendentes = PurchaseOrderIntegration.objects.filter(
        origem="backoffice",
        metodo_criacao__in=["sistema", "sistema_full_flow"],
    )

    for po in pendentes:
        service.processar_pedido_para_financeiro(po)


@shared_task(bind=True, max_retries=3)
def encerrar_pedido_task(self, numero_pedido: str, item_pedido: str,
                         numero_nf_servico: str, id_nf_servico: int):
    """
    Task assíncrona para encerrar pedido de compra
    """
    try:
        logger.info(f"Encerrando pedido assincronamente: {numero_pedido}")
        service = PurchaseOrderClosureService()
        resultado = service.encerrar_pedido_automaticamente(
            numero_pedido=numero_pedido,
            item_pedido=item_pedido,
            numero_nf_servico=numero_nf_servico,
            id_nf_servico=id_nf_servico
        )

        return {
            'status': resultado.status,
            'numero_pedido': numero_pedido,
            'mensagem': resultado.mensagem_erro if resultado.status == 'failed' else 'Sucesso'
        }
    except Exception as exc:
        logger.error(f"Erro ao encerrar pedido: {str(exc)}")
        raise self.retry(exc=exc, countdown=60)


@shared_task
def reprocessar_falhas_task():
    """
    Task periódica para reprocessar encerramentos que falharam
    """
    logger.info("Reprocessando encerramentos que falharam...")
    service = PurchaseOrderClosureService()
    resultados = service.reprocessar_falhas()

    return {
        'total_reprocessados': len(resultados),
        'sucessos': len([r for r in resultados if r.status == 'success']),
        'falhas': len([r for r in resultados if r.status == 'failed'])
    }