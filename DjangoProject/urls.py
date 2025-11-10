from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from attachments.views import AttachmentTransferViewSet
from purchase_orders.views import (
    PurchaseOrderClosureViewSet,
    PurchaseOrderIntegrationViewSet,
    PurchaseOrderFinanceMapViewSet,
)

router = DefaultRouter()
router.register(r"attachments", AttachmentTransferViewSet, basename="attachments")
router.register(r"purchase-orders/closure", PurchaseOrderClosureViewSet, basename="po-closure")
router.register(r"purchase-orders/integrations", PurchaseOrderIntegrationViewSet, basename="po-integrations")
router.register(r"purchase-orders/finance-map", PurchaseOrderFinanceMapViewSet, basename="po-finance-map")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(router.urls)),
]
