import logging

logger = logging.getLogger(__name__)

"""
Observação importante sobre disparo automático de encerramento de Pedido de Compra
---------------------------------------------------------------------------------

Antes: este módulo registrava um receiver de post_save com sender="seu_app.NotaFiscalServico",
que é um placeholder e quebra o carregamento do Django porque o modelo não existe.

Agora: removemos o receiver inválido. Existem duas formas recomendadas de disparar o
encerramento:

1) Chamada explícita a partir da integração que cria a NF de Serviço no Omie:
   from purchase_orders.signals import disparar_encerramento_por_integracao
   disparar_encerramento_por_integracao(numero_pedido, item_pedido, numero_nf_servico, id_nf_servico)

2) Webhook/retorno do Omie (quando disponível), chamando a mesma função acima.

Se, no futuro, você tiver um modelo Django real que represente a NF de Serviço,
você pode restaurar um signal apontando para esse modelo real.
"""


def disparar_encerramento_por_integracao(
    numero_pedido: str,
    item_pedido: str,
    numero_nf_servico: str,
    id_nf_servico: int,
):
    """Utilitário para ser chamado pela integração após criar a NF de Serviço no Omie."""
    from .services import PurchaseOrderClosureService

    logger.info(
        "Disparo explícito de encerramento de PC por integração: "
        f"PC={numero_pedido} item={item_pedido} NF={numero_nf_servico} id={id_nf_servico}"
    )
    service = PurchaseOrderClosureService()
    return service.encerrar_pedido_automaticamente(
        numero_pedido=numero_pedido,
        item_pedido=item_pedido,
        numero_nf_servico=numero_nf_servico,
        id_nf_servico=id_nf_servico,
    )