import requests
import logging
from typing import Dict, List, Optional, Any
from decouple import config

logger = logging.getLogger(__name__)


class OmieAPIException(Exception):
    """Exceção customizada para erros da API Omie"""
    pass


class OmieAPIClient:
    """
    Cliente para consumir as APIs do Omie ERP
    Documentação: https://developer.omie.com.br/
    """

    def __init__(self):
        self.app_key = config('OMIE_APP_KEY')
        self.app_secret = config('OMIE_APP_SECRET')
        self.base_url = config('OMIE_API_BASE_URL', default='https://app.omie.com.br/api/v1/')
        # Configurações para encerramento de Pedido de Compra
        # Algumas contas usam cStatus="Fechado" e outras "Encerrado". Torna-se configurável por env.
        self.po_close_status = config('OMIE_PO_CLOSE_STATUS', default='Encerrado')
        self.po_close_call = config('OMIE_PO_CLOSE_CALL', default='AlterarPedidoCompra')
        self.po_close_endpoint = config('OMIE_PO_CLOSE_ENDPOINT', default='produtos/pedidocompra/')

    def _make_request(self, endpoint: str, call: str, params: Dict[str, Any]) -> Dict:
        """
        Método genérico para fazer requisições à API Omie

        Args:
            endpoint: Endpoint da API (ex: 'produtos/nfconsultar/')
            call: Nome da chamada da API (ex: 'ListarRecebimentos')
            params: Parâmetros específicos da chamada

        Returns:
            Dict com a resposta da API
        """
        url = f"{self.base_url}{endpoint}"

        payload = {
            "call": call,
            "app_key": self.app_key,
            "app_secret": self.app_secret,
            "param": [params]
        }

        try:
            logger.info(f"Chamando API Omie: {call} - Endpoint: {endpoint}")
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()

            data = response.json()

            # Verifica se houve erro na resposta da Omie
            if 'faultstring' in data:
                raise OmieAPIException(f"Erro Omie: {data['faultstring']}")

            logger.info(f"Resposta recebida com sucesso: {call}")
            return data

        except requests.exceptions.RequestException as e:
            logger.error(f"Erro na requisição à API Omie: {str(e)}")
            raise OmieAPIException(f"Erro na comunicação com Omie: {str(e)}")

    # ===== RF-001: Métodos para Gestão de Anexos =====

    def listar_anexos(self, tabela: str, n_id: int) -> List[Dict]:
        """
        Lista anexos de um registro específico

        Args:
            tabela: Nome da tabela (exato): 'com-recebimento' ou 'conta_a_pagar'. Outros valores podem existir em módulos específicos.
            n_id: ID do registro

        Returns:
            Lista de anexos
        """
        allowed = {"conta_a_pagar", "com-recebimento"}
        if tabela not in allowed:
            logger.warning(
                "Valor de cTabela possivelmente incorreto: %s. Exemplos válidos comuns: %s. Prosseguindo assim mesmo...",
                tabela, sorted(allowed)
            )
        params = {
            "cTabela": tabela,
            "nId": n_id
        }

        response = self._make_request(
            endpoint='geral/anexo/',
            call='ListarAnexo',
            params=params
        )

        return response.get('anexos', [])

    def obter_anexo(self, n_id_anexo: int) -> Dict:
        """
        Obtém o conteúdo de um anexo específico (base64)

        Args:
            n_id_anexo: ID do anexo

        Returns:
            Dict com dados do anexo incluindo cArquivo (base64)
        """
        params = {
            "nIdAnexo": n_id_anexo
        }

        response = self._make_request(
            endpoint='geral/anexo/',
            call='ObterAnexo',
            params=params
        )

        return response

    def incluir_anexo(self, tabela: str, n_id: int, nome_arquivo: str,
                      arquivo_base64: str, descricao: Optional[str] = None) -> Dict:
        """
        Inclui um anexo em um registro

        Args:
            tabela: Nome da tabela de destino (exato): 'conta_a_pagar' ou 'com-recebimento'.
            n_id: ID do registro de destino
            nome_arquivo: Nome do arquivo
            arquivo_base64: Conteúdo do arquivo em base64
            descricao: Descrição opcional do anexo

        Returns:
            Dict com resposta da inclusão
        """
        allowed = {"conta_a_pagar", "com-recebimento"}
        if tabela not in allowed:
            logger.warning(
                "Valor de cTabela possivelmente incorreto ao incluir anexo: %s. Exemplos válidos comuns: %s.",
                tabela, sorted(allowed)
            )
        params = {
            "cTabela": tabela,
            "nId": n_id,
            "cNomeArquivo": nome_arquivo,
            "cArquivo": arquivo_base64,
        }

        if descricao:
            params["cDescricao"] = descricao

        response = self._make_request(
            endpoint='geral/anexo/',
            call='IncluirAnexo',
            params=params
        )

        return response

    def listar_recebimentos(self, pagina: int = 1, registros_por_pagina: int = 50,
                            filtros: Optional[Dict] = None) -> Dict:
        """
        Lista recebimentos de NF-e

        Args:
            pagina: Número da página
            registros_por_pagina: Quantidade de registros por página
            filtros: Filtros adicionais (opcional)

        Returns:
            Dict com lista de recebimentos
        """
        params = {
            "nPagina": pagina,
            "nRegPorPagina": registros_por_pagina
        }

        if filtros:
            params.update(filtros)

        response = self._make_request(
            endpoint='produtos/nfconsultar/',
            call='ListarRecebimentos',
            params=params
        )

        return response

    def consultar_recebimento(self, n_id_receb: int) -> Dict:
        """
        Consulta um recebimento específico pelo ID

        Args:
            n_id_receb: ID do recebimento

        Returns:
            Dict com dados do recebimento
        """
        params = {
            "nIdReceb": n_id_receb
        }

        response = self._make_request(
            endpoint='produtos/nfconsultar/',
            call='ConsultarRecebimento',
            params=params
        )

        return response

    # ===== RF-002: Métodos para Pedidos de Compra =====

    def consultar_pedido_compra(self, numero_pedido: str) -> Dict:
        """
        Consulta um pedido de compra pelo número

        Args:
            numero_pedido: Número do pedido de compra

        Returns:
            Dict com dados do pedido
        """
        params = {
            "cNumero": numero_pedido
        }

        response = self._make_request(
            endpoint='produtos/pedidocompra/',
            call='ConsultarPedidoCompra',
            params=params
        )

        return response

    def encerrar_pedido_compra(self, numero_pedido: str, codigo_item: Optional[str] = None) -> Dict:
        """
        Encerra (finaliza) um pedido de compra ou um item específico.
        Por diferenças entre contas Omie, o campo/valor de status e até o call/endpoint
        podem variar. Tornamos isso configurável via env/settings:
          - OMIE_PO_CLOSE_STATUS (default: "Encerrado")
          - OMIE_PO_CLOSE_CALL (default: "AlterarPedidoCompra")
          - OMIE_PO_CLOSE_ENDPOINT (default: "produtos/pedidocompra/")

        Args:
            numero_pedido: Número do pedido de compra
            codigo_item: Código do item (opcional, se quiser encerrar apenas um item)

        Returns:
            Dict com resposta do encerramento
        """
        status_val = (self.po_close_status or 'Encerrado').strip()
        if status_val not in {"Encerrado", "Fechado"}:
            logger.warning(
                "Valor de status para encerramento não usual: %s. Esperado: 'Encerrado' ou 'Fechado' dependendo da conta.",
                status_val,
            )

        params = {
            "cNumero": numero_pedido,
            "cStatus": status_val,
        }

        if codigo_item:
            params["cCodItem"] = codigo_item

        logger.info(
            "Fechando pedido de compra no Omie: numero=%s, item=%s, status=%s, call=%s, endpoint=%s",
            numero_pedido,
            codigo_item or "<todos>",
            status_val,
            self.po_close_call,
            self.po_close_endpoint,
        )

        response = self._make_request(
            endpoint=self.po_close_endpoint,
            call=self.po_close_call,
            params=params,
        )

        return response

    def consultar_contas_pagar(self, codigo_lancamento: int) -> Dict:
        """
        Consulta um lançamento de contas a pagar

        Args:
            codigo_lancamento: Código do lançamento

        Returns:
            Dict com dados do contas a pagar
        """
        params = {
            "nCodTitulo": codigo_lancamento
        }

        response = self._make_request(
            endpoint='financas/contapagar/',
            call='ConsultarContaPagar',
            params=params
        )

        return response