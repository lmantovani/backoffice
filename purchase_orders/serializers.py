from rest_framework import serializers
from .models import PurchaseOrderIntegration, PurchaseOrderFinanceMap


class PurchaseOrderIntegrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseOrderIntegration
        fields = "__all__"


class PurchaseOrderFinanceMapSerializer(serializers.ModelSerializer):
    purchase_order = PurchaseOrderIntegrationSerializer()

    class Meta:
        model = PurchaseOrderFinanceMap
        fields = "__all__"
