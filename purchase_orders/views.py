import json
import logging
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.conf import settings

from .models import (
    PurchaseOrderClosureLog,
    PurchaseOrderIntegration,
    PurchaseOrderFinanceMap,
)
from .serializers import (
    PurchaseOrderClosureLogSerializer,
    PurchaseOrderIntegrationSerializer,
    PurchaseOrderFinanceMapSerializer,
    PurchaseOrderFullFlowSerializer,
)
from omie_api.client import OmieAPIException, OmieAPIClient
from .services import (
    FullFlowPurchaseOrderService,
    PurchaseOrderRobotService,
    SupplierService,
    PurchaseOrderClosureService,
    CategoryService,
    BuyerService,
    ProductService,
)
from .tasks import encerrar_pedido_task
from .tasks import monitorar_pedido_e_processar


logger = logging.getLogger(__name__)

@login_required
def purchase_orders_page(request):
    return render(request, "pages/purchase_orders.html")


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
        raw_pedido = request.data.get("pedido")
        if isinstance(raw_pedido, str):
            try:
                pedido_data = json.loads(raw_pedido)
            except json.JSONDecodeError:
                return Response(
                    {"detail": "Campo 'pedido' deve conter um JSON válido."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        elif isinstance(raw_pedido, dict):
            pedido_data = raw_pedido
        else:
            pedido_data = {}

        serializer_input = PurchaseOrderFullFlowSerializer(data=pedido_data)
        if not serializer_input.is_valid():
            return Response(serializer_input.errors, status=status.HTTP_400_BAD_REQUEST)

        arquivos = request.FILES.getlist("anexos")

        try:
            po = service.criar_pedido_com_anexos(serializer_input.validated_data, arquivos)
            # Tenta processar imediatamente; se ainda não finalizado, agenda monitoramento assíncrono
            fmap = service.processar_pedido_para_financeiro(po)
            if not fmap:
                try:
                    monitorar_pedido_e_processar.delay(po.id)
                except Exception:
                    logger.exception("Falha ao enfileirar monitoramento do pedido para processamento financeiro")
        except OmieAPIException as exc:
            logger.exception("Omie retornou erro ao executar full-flow de pedido")
            return Response(
                {"detail": f"Falha ao integrar com a Omie: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except Exception:
            logger.exception("Erro inesperado ao processar pedido full-flow")
            return Response(
                {"detail": "Erro interno ao processar o pedido. Tente novamente."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

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

class SupplierListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        search = request.query_params.get("search") or request.query_params.get("q") or ""

        try:
            suppliers = SupplierService.list_suppliers(search=search)
        except OmieAPIException as exc:
            logger.exception("Erro ao consultar fornecedores na Omie")
            return Response(
                {"detail": f"Erro ao consultar fornecedores na Omie: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(suppliers)

class CategoryListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        search = request.query_params.get("search", "")
        try:
            data = CategoryService.list_categories(search)
        except OmieAPIException as exc:
            logger.exception("Erro ao listar categorias no Omie")
            return Response({"detail": f"Erro ao consultar categorias: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(data)


class BuyerListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        search = request.query_params.get("search", "")
        try:
            data = BuyerService.list_buyers(search)
        except OmieAPIException as exc:
            logger.exception("Erro ao listar compradores no Omie")
            return Response({"detail": f"Erro ao consultar compradores: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(data)

class ProductListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        search = request.query_params.get("search", "")
        try:
            page = int(request.query_params.get("page", 1))
        except (TypeError, ValueError):
            page = 1
        try:
            per_page = int(request.query_params.get("per_page", 50))
        except (TypeError, ValueError):
            per_page = 50
        try:
            data = ProductService.list_products(search, page=page, per_page=per_page)
        except OmieAPIException as exc:
            logger.exception("Erro ao listar produtos no Omie")
            return Response({"detail": f"Erro ao consultar produtos: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(data)


# Endpoint simples de debug para listar anexos de um pedido de compra na Omie
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def listar_anexos_pedido(request, pk: int):
    po = get_object_or_404(PurchaseOrderIntegration, pk=pk)
    if not po.ncodped_omie:
        return Response({"detail": "Pedido local não possui ncodped_omie registrado."}, status=status.HTTP_400_BAD_REQUEST)

    client = OmieAPIClient.from_settings()
    try:
        # Omie usa cTabela="pedido-compra" e identificador do documento (nCodPed) no campo nCodigo/nId conforme o método
        anexos = client.listar_anexos("pedido-compra", po.ncodped_omie)
    except OmieAPIException as exc:
        logger.exception("Erro ao listar anexos do pedido %s na Omie", po.ncodped_omie)
        return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    return Response({
        "pedido_local_id": po.id,
        "ncodped_omie": po.ncodped_omie,
        "anexos": anexos,
    })
