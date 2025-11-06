from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .services import AttachmentTransferService
from .tasks import transferir_anexos_task
import logging

logger = logging.getLogger(__name__)


class AttachmentTransferViewSet(viewsets.ViewSet):
    """
    ViewSet para operações de transferência de anexos (RF-001).
    Usa apenas actions customizadas; não lista modelos.
    Também oferece inclusão de anexo (upload base64) para suportar o caso de anexar PDF no pedido de compra.
    """

    @action(detail=False, methods=['post'])
    def transferir(self, request):
        """
        Endpoint para disparar manualmente uma transferência de anexos

        POST /api/attachments/transferir/
        {
            "origem_id": 12345,
            "destino_id": 67890,
            "origem_tabela": "com-recebimento" | "pedido-compra" | ...,  # opcional, default com-recebimento
            "destino_tabela": "conta_a_pagar",  # opcional, default conta_a_pagar
            "assincrono": true  # opcional
        }
        """
        origem_id = request.data.get('origem_id')
        destino_id = request.data.get('destino_id')
        origem_tabela = request.data.get('origem_tabela', 'com-recebimento')
        destino_tabela = request.data.get('destino_tabela', 'conta_a_pagar')
        assincrono = request.data.get('assincrono', False)

        if not origem_id or not destino_id:
            return Response(
                {'erro': 'origem_id e destino_id são obrigatórios'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if assincrono:
            # Processa de forma assíncrona
            task = transferir_anexos_task.delay(origem_id, destino_id)
            return Response({
                'mensagem': 'Transferência iniciada de forma assíncrona',
                'task_id': task.id
            }, status=status.HTTP_202_ACCEPTED)
        else:
            # Processa de forma síncrona
            service = AttachmentTransferService()
            resultado = service.transferir_anexos(origem_id, destino_id, origem_tabela=origem_tabela, destino_tabela=destino_tabela)

            return Response({
                'status': resultado.status,
                'anexos_transferidos': resultado.anexos_sucesso,
                'total_anexos': resultado.total_anexos,
                'mensagem_erro': resultado.mensagem_erro,
                'detalhes': resultado.detalhes,
                'log_id': resultado.id
            })

    @action(detail=False, methods=['post'])
    def processar_pendentes(self, request):
        """
        Endpoint para processar todas as transferências pendentes
        """
        service = AttachmentTransferService()
        resultados = service.processar_transferencias_pendentes()

        return Response({
            'total_processados': len(resultados),
            'sucessos': len([r for r in resultados if r.status == 'success']),
            'falhas': len([r for r in resultados if r.status == 'failed'])
        })

    @action(detail=False, methods=['post'])
    def incluir(self, request):
        """
        Inclui (faz upload) de um anexo em qualquer tabela suportada pela Omie.
        POST /api/attachments/incluir/
        {
          "tabela": "pedido-compra",
          "n_id": 123456,
          "nome_arquivo": "documento.pdf",
          "arquivo_base64": "..."
        }
        """
        tabela = request.data.get('tabela')
        n_id = request.data.get('n_id')
        nome_arquivo = request.data.get('nome_arquivo')
        arquivo_base64 = request.data.get('arquivo_base64')
        descricao = request.data.get('descricao')

        if not all([tabela, n_id, nome_arquivo, arquivo_base64]):
            return Response({'erro': 'tabela, n_id, nome_arquivo e arquivo_base64 são obrigatórios'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            from omie_api.client import OmieAPIClient
            client = OmieAPIClient()
            resp = client.incluir_anexo(
                tabela=tabela,
                n_id=int(n_id),
                nome_arquivo=nome_arquivo,
                arquivo_base64=arquivo_base64,
                descricao=descricao
            )
            return Response(resp)
        except Exception as e:
            logger.exception("Falha ao incluir anexo")
            return Response({'erro': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)