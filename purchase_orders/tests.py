from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from unittest.mock import patch


class PurchaseOrderClosureAPITests(APITestCase):
    def setUp(self):
        self.url_encerrar = reverse('purchase-order-closure-encerrar')
        self.url_reprocessar = reverse('purchase-order-closure-reprocessar-falhas')

    @patch('purchase_orders.services.OmieAPIClient')
    def test_encerrar_pedido_success_sync(self, MockClient):
        # Arrange: mock Omie client behavior
        instance = MockClient.return_value
        instance.consultar_pedido_compra.return_value = {'cStatus': 'Aberto'}
        instance.encerrar_pedido_compra.return_value = {'ok': True}

        payload = {
            'numero_pedido': 'PO123',
            'item_pedido': '001',
            'numero_nf_servico': 'NF789',
            'id_nf_servico': 999,
            'assincrono': False,
        }

        # Act
        resp = self.client.post(self.url_encerrar, data=payload, format='json')

        # Assert
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['status'], 'success')
        self.assertEqual(resp.data['numero_pedido'], 'PO123')
        instance.consultar_pedido_compra.assert_called_once_with('PO123')
        instance.encerrar_pedido_compra.assert_called_once_with(numero_pedido='PO123', codigo_item='001')

    def test_encerrar_pedido_missing_fields(self):
        # Missing required fields
        resp = self.client.post(self.url_encerrar, data={'numero_pedido': 'PO123'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Campos obrigatórios', resp.data['erro'])

    @patch('purchase_orders.services.OmieAPIClient')
    def test_reprocessar_falhas_endpoint(self, MockClient):
        # No logs created yet, so reprocess should return zeros
        resp = self.client.post(self.url_reprocessar, data={}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('total_reprocessados', resp.data)
        self.assertIn('sucessos', resp.data)
        self.assertIn('falhas', resp.data)
