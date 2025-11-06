from django.shortcuts import render
from django.contrib.auth.decorators import login_required


@login_required
def home(request):
    """Página inicial simples com links úteis (Admin e API). Requer login."""
    context = {}
    return render(request, "home.html", context)


@login_required
def attachments_page(request):
    """Página de Anexos (UI) para acionar/processar operações relacionadas a anexos."""
    context = {
        "api_transferir_url": "/api/attachments/transferir/",
        "api_base": "/api/attachments/",
    }
    return render(request, "pages/attachments.html", context)


@login_required
def purchase_orders_page(request):
    """Página de Pedidos de Compra (UI) para operações de encerramento."""
    context = {
        "api_base": "/api/purchase-orders/",
    }
    return render(request, "pages/purchase_orders.html", context)
