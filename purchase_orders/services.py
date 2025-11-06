import logging
from typing import Optional
from django.db import models
from omie_api.client import OmieAPIClient, OmieAPIException
from .models import PurchaseOrderClosureLog

logger = logging.getLogger(__name__)


class PurchaseOrderClosureService:
    """
    Serviço para encerrar automaticamente pedidos de compra (RF-002)
    """

    def __init__(self):
        self.client = OmieAPIClient()

    def encerrar_pedido_automaticamente(
            self,
            numero_pedido: str,
            item_pedido: Optional[str],
            numero_nf_servico: str,
            id_nf_servico: int
    ) -> PurchaseOrderClosureLog:
        """
        Encerra um pedido de compra automaticamente quando uma NF de serviço é lançada

        Args:
            numero_pedido: Número do pedido de compra
            item_pedido: Item do pedido (opcional)
            numero_nf_servico: Número da NF de serviço
            id_nf_servico: ID da NF de serviço no Omie

        Returns:
            PurchaseOrderClosureLog com o resultado da operação
        """
        # Cria o log de encerramento
        log = PurchaseOrderClosureLog.objects.create(
            numero_pedido=numero_pedido,
            item_pedido=item_pedido,
            numero_nf_servico=numero_nf_servico,
            id_nf_servico=id_nf_servico,
            status='pending'
        )

        try:
            log.mark_as_processing()

            # Consulta o pedido de compra para verificar o status atual
            logger.info(f"Consultando pedido de compra: {numero_pedido}")
            pedido = self.client.consultar_pedido_compra(numero_pedido)

            status_atual = pedido.get('cStatus', '')
            logger.info(f"Status atual do pedido {numero_pedido}: {status_atual}")

            # Verifica se já está encerrado
            if status_atual.lower() in ['fechado', 'encerrado', 'finalizado']:
                logger.info(f"Pedido {numero_pedido} já está encerrado")
                log.mark_as_success({
                    'mensagem': 'Pedido já estava encerrado',
                    'status_anterior': status_atual
                })
                return log

            # Encerra o pedido
            logger.info(f"Encerrando pedido {numero_pedido}")
            resultado = self.client.encerrar_pedido_compra(
                numero_pedido=numero_pedido,
                codigo_item=item_pedido
            )

            log.mark_as_success({
                'status_anterior': status_atual,
                'status_novo': self.client.po_close_status or 'Encerrado',
                'item_encerrado': item_pedido,
                'resultado_api': resultado
            })

            logger.info(f"Pedido {numero_pedido} encerrado com sucesso")
            return log

        except OmieAPIException as e:
            logger.error(f"Erro na API Omie ao encerrar pedido {numero_pedido}: {str(e)}")
            log.mark_as_failed(str(e))
            return log

        except Exception as e:
            logger.error(f"Erro inesperado ao encerrar pedido {numero_pedido}: {str(e)}")
            log.mark_as_failed(f"Erro inesperado: {str(e)}")
            return log

    def reprocessar_falhas(self) -> list:
        """
        Reprocessa encerramentos que falharam
        """
        logs_falhos = PurchaseOrderClosureLog.objects.filter(
            status='failed'
        ).filter(
            tentativas__lt=models.F('max_tentativas')
        )

        resultados = []
        for log in logs_falhos:
            resultado = self.encerrar_pedido_automaticamente(
                numero_pedido=log.numero_pedido,
                item_pedido=log.item_pedido,
                numero_nf_servico=log.numero_nf_servico,
                id_nf_servico=log.id_nf_servico
            )
            resultados.append(resultado)

        return resultados