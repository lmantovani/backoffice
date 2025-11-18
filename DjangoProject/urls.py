from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect, render
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from rest_framework.routers import DefaultRouter
from purchase_orders.views import SupplierListView

from attachments.views import AttachmentTransferViewSet
from purchase_orders.views import (
    PurchaseOrderClosureViewSet,
    PurchaseOrderIntegrationViewSet,
    PurchaseOrderFinanceMapViewSet,
    purchase_orders_page,
)


router = DefaultRouter()
router.register(r"attachments", AttachmentTransferViewSet, basename="attachments")
router.register(r"purchase-orders/closure", PurchaseOrderClosureViewSet, basename="po-closure")
router.register(r"purchase-orders/integrations", PurchaseOrderIntegrationViewSet, basename="po-integrations")
router.register(r"purchase-orders/finance-map", PurchaseOrderFinanceMapViewSet, basename="po-finance-map")


@login_required
def home_view(request):
    # usa teu templates/home.html como dashboard inicial
    return render(request, "home.html")


def root_view(request):
    # se logado, manda pra home_view
    if request.user.is_authenticated:
        return home_view(request)
    # senão, joga pro login customizado
    return redirect("login")


def home_redirect(request):
    # para links que apontam pra /home/
    return redirect("home")


def attachments_redirect(request):
    # se alguém bater em /attachments/, você pode:
    # - mandar para a API, ou
    # - futuramente renderizar uma página HTML
    # por enquanto, vamos só mandar pro endpoint da API pra não dar 404
    return redirect("/api/attachments/")


def purchase_orders_redirect(request):
    # idem p/ /purchase-orders/
    return redirect("/api/purchase-orders/integrations/")


urlpatterns = [
    # raiz e alias /home/
    path("", root_view, name="home"),
    path("home/", home_redirect, name="home_alias"),
    path("purchase-orders/", purchase_orders_page, name="purchase_orders_ui"),

    # login/logout com teu template em templates/registration/login.html
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path(
        "logout/",
        auth_views.LogoutView.as_view(),
        name="logout",
    ),

    # reset de senha (porque o template referencia password_reset)
    path("password_reset/", auth_views.PasswordResetView.as_view(), name="password_reset"),
    path(
        "password_reset/done/",
        auth_views.PasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),

    # rotas "amigáveis" para não dar 404 nos links existentes
    path("attachments/", attachments_redirect, name="attachments_page"),

    # admin e API
    path("admin/", admin.site.urls),
    path("api/", include(router.urls)),
    path("api/suppliers/", SupplierListView.as_view(), name="suppliers-list"),
]
