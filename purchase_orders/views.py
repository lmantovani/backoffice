# apps/purchase_orders/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import PurchaseOrderClosureLog
from .services import PurchaseOrderClosureService
from .tasks import encerrar_pedido_task
import logging

logger = logging.getLogger(__name__)


class PurchaseOrderClosureViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet para consultar logs de encerramento de pedidos
    """
    queryset = PurchaseOrderClosureLog.objects.all()

    @action(detail=False, methods=['post'])
    def encerrar(self, request):
        """
        Endpoint para disparar manualmente o encerramento de um pedido

        POST /api/purchase-orders/encerrar/
        {
            "numero_pedido": "123456",
            "item_pedido": "001",  # opcional
            "numero_nf_servico": "789",
            "id_nf_servico": 999,
            "assincrono": true  # opcional
        }
        """
        numero_pedido = request.data.get('numero_pedido')
        item_pedido = request.data.get('item_pedido')
        numero_nf_servico = request.data.get('numero_nf_servico')
        id_nf_servico = request.data.get('id_nf_servico')
        assincrono = request.data.get('assincrono', False)

        if not all([numero_pedido, numero_nf_servico, id_nf_servico]):
            return Response(
                {'erro': 'Campos obrigatórios: numero_pedido, numero_nf_servico, id_nf_servico'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if assincrono:
            # Processa de forma assíncrona
            task = encerrar_pedido_task.delay(
                numero_pedido, item_pedido, numero_nf_servico, id_nf_servico
            )
            return Response({
                'mensagem': 'Encerramento iniciado de forma assíncrona',
                'task_id': task.id
            }, status=status.HTTP_202_ACCEPTED)
        else:
            # Processa de forma síncrona
            service = PurchaseOrderClosureService()
            resultado = service.encerrar_pedido_automaticamente(
                numero_pedido=numero_pedido,
                item_pedido=item_pedido,
                numero_nf_servico=numero_nf_servico,
                id_nf_servico=id_nf_servico
            )

            return Response({
                'status': resultado.status,
                'numero_pedido': numero_pedido,
                'mensagem_erro': resultado.mensagem_erro,
                'detalhes': resultado.detalhes
            })

    @action(detail=False, methods=['post'])
    def reprocessar_falhas(self, request):
        """
        Endpoint para reprocessar encerramentos que falharam
        """
        service = PurchaseOrderClosureService()
        resultados = service.reprocessar_falhas()

        return Response({
            'total_reprocessados': len(resultados),
            'sucessos': len([r for r in resultados if r.status == 'success']),
            'falhas': len([r for r in resultados if r.status == 'failed'])
        })