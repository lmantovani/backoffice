# purchase_orders/serializers.py

from rest_framework import serializers
from .models import (
    PurchaseOrderClosureLog,
    PurchaseOrderIntegration,
    PurchaseOrderFinanceMap,
)

class PurchaseOrderClosureLogSerializer(serializers.ModelSerializer):
    """
    Serializa logs de fechamento de pedidos.
    """
    class Meta:
        model = PurchaseOrderClosureLog
        fields = "__all__"


class PurchaseOrderIntegrationSerializer(serializers.ModelSerializer):
    """
    Serializa integrações de pedidos (backoffice ↔ Omie).
    """
    class Meta:
        model = PurchaseOrderIntegration
        fields = "__all__"


class PurchaseOrderFinanceMapSerializer(serializers.ModelSerializer):
    """
    Serializa mapeamentos de pedidos para financeiro.
    """
    class Meta:
        model = PurchaseOrderFinanceMap
        fields = "__all__"


class PurchaseOrderItemSerializer(serializers.Serializer):
    nItem = serializers.IntegerField(min_value=1)
    codigo_produto = serializers.CharField()
    descricao = serializers.CharField(max_length=255)
    nQtdeItem = serializers.DecimalField(max_digits=14, decimal_places=4)
    nValUnitario = serializers.DecimalField(max_digits=14, decimal_places=4)
    nValTotal = serializers.DecimalField(max_digits=14, decimal_places=4)
    unidade = serializers.CharField(max_length=10, required=False, allow_blank=True)
    cCodIntItem = serializers.CharField(required=False, allow_blank=True)
    nPercentualDesconto = serializers.DecimalField(max_digits=5, decimal_places=2, required=False)


class PurchaseOrderInstallmentSerializer(serializers.Serializer):
    nParcela = serializers.IntegerField(min_value=1)
    dDataVencimento = serializers.CharField()
    nValorParcela = serializers.DecimalField(max_digits=14, decimal_places=2)


class PurchaseOrderHeaderSerializer(serializers.Serializer):
    cCodIntPed = serializers.CharField(required=False, allow_blank=True)
    codigo_cliente_fornecedor = serializers.IntegerField()
    dDtEmissao = serializers.CharField()
    dDtPrevisao = serializers.CharField()
    nQtdeParcelas = serializers.IntegerField(min_value=1)
    observacao = serializers.CharField(required=False, allow_blank=True)
    codigo_categoria = serializers.CharField(required=False, allow_blank=True)
    cCodComprador = serializers.CharField(required=False, allow_blank=True)
    nValorTotal = serializers.DecimalField(max_digits=14, decimal_places=2)
    nValorMercadoria = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)
    nValorDesconto = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)
    nValorFrete = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)


class PurchaseOrderFullFlowSerializer(serializers.Serializer):
    cabecalho = PurchaseOrderHeaderSerializer()
    det = PurchaseOrderItemSerializer(many=True)
    parcelas = PurchaseOrderInstallmentSerializer(many=True)
    informacoes_adicionais = serializers.DictField(required=False)

    def validate(self, attrs):
        cab = attrs.get("cabecalho", {})
        itens = attrs.get("det") or []
        parcelas = attrs.get("parcelas") or []
        if not itens:
            raise serializers.ValidationError("Pedido precisa de ao menos 1 item")
        if len(parcelas) != cab.get("nQtdeParcelas"):
            raise serializers.ValidationError("Quantidade de parcelas não bate com nQtdeParcelas")
        return attrs
