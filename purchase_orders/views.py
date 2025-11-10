import logging
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import (
    PurchaseOrderClosureLog,
    PurchaseOrderIntegration,
    PurchaseOrderFinanceMap,
)
from .serializers import (
    PurchaseOrderClosureLogSerializer,
    PurchaseOrderIntegrationSerializer,
    PurchaseOrderFinanceMapSerializer,
)
from .services import (
    FullFlowPurchaseOrderService,
    PurchaseOrderRobotService,
)

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

class PurchaseOrderIntegrationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PurchaseOrderIntegration.objects.all().order_by("-created_at")
    serializer_class = PurchaseOrderIntegrationSerializer

    @action(detail=False, methods=["post"], url_path="full-flow")
    def full_flow(self, request):
        service = FullFlowPurchaseOrderService()
        pedido_data = request.data.get("pedido") or {}
        arquivos = request.FILES.getlist("anexos")
        po = service.criar_pedido_com_anexos(pedido_data, arquivos)
        service.processar_pedido_para_financeiro(po)
        serializer = self.get_serializer(po)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="run-robot")
    def run_robot(self, request):
        service = PurchaseOrderRobotService()
        service.processar()
        return Response({"detail": "Robô executado."}, status=status.HTTP_200_OK)


class PurchaseOrderFinanceMapViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = (
        PurchaseOrderFinanceMap.objects.select_related("purchase_order")
        .all()
        .order_by("-created_at")
    )
    serializer_class = PurchaseOrderFinanceMapSerializer
