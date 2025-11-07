"""
URL configuration for DjangoProject project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic.base import RedirectView
from rest_framework.routers import DefaultRouter, routers
from attachments.views import AttachmentTransferViewSet
from purchase_orders.views import PurchaseOrderClosureViewSet
from BackOffice import views as backoffice_views
from purchase_orders.views import (
    PurchaseOrderIntegrationViewSet,
    PurchaseOrderFinanceMapViewSet,
)

router = DefaultRouter()
router.register(r'attachments', AttachmentTransferViewSet, basename='attachment-transfer')
router.register(r'purchase-orders', PurchaseOrderClosureViewSet, basename='purchase-order-closure')
router.register(r"purchase-orders/integrations", PurchaseOrderIntegrationViewSet, basename="po-integrations")
router.register(r"purchase-orders/finance-map", PurchaseOrderFinanceMapViewSet, basename="po-finance-map"

urlpatterns = [
    path('', RedirectView.as_view(url='/home/', permanent=False)),
    path('home/', backoffice_views.home, name='home'),
    path('attachments/', backoffice_views.attachments_page, name='attachments_page'),
    path('purchase-orders/', backoffice_views.purchase_orders_page, name='purchase_orders_page'),
    path('admin/', admin.site.urls),
    path('api/', include(router.urls)),
    # Autenticação padrão do Django (login/logout)
    path('accounts/', include('django.contrib.auth.urls')),
    # Login/logout para o browsable API do DRF
    path('api-auth/', include('rest_framework.urls', namespace='rest_framework')),
]
