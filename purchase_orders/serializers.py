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
