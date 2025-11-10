# omie_api/client.py

import base64
import logging
from typing import Any, Dict, List, Optional

import requests
from decouple import config

logger = logging.getLogger(__name__)


class OmieAPIException(Exception):
    """Exceção customizada para erros da API Omie."""
    pass


class OmieAPIClient:
    def __init__(self):
        self.app_key = config("OMIE_APP_KEY")
        self.app_secret = config("OMIE_APP_SECRET")
        self.base_url = config(
            "OMIE_API_BASE_URL",
            default="https://app.omie.com.br/api/v1/",
        )

        # Config RF-002 (encerramento pedido)
        self.po_close_status = config("OMIE_PO_CLOSE_STATUS", default="Encerrado")
        self.po_close_call = config("OMIE_PO_CLOSE_CALL", default="AlterarPedidoCompra")
        self.po_close_endpoint = config(
            "OMIE_PO_CLOSE_ENDPOINT",
            default="produtos/pedidocompra/",
        )

    @classmethod
    def from_settings(cls) -> "OmieAPIClient":
        return cls()

    # ------------ Helpers básicos ------------

    def _post_raw(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        try:
            resp = requests.post(url, json=payload, timeout=60)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.error("Erro HTTP Omie: %s", exc)
            raise OmieAPIException(f"Erro HTTP ao chamar Omie: {exc}") from exc

        data = resp.json()
        if isinstance(data, dict) and "faultstring" in data:
            logger.error("Erro Omie: %s", data)
            raise OmieAPIException(data["faultstring"])
        return data

    def _call(self, endpoint: str, call: str, params: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "call": call,
            "app_key": self.app_key,
            "app_secret": self.app_secret,
            "param": [params],
        }
        logger.info("Omie API call=%s endpoint=%s", call, endpoint)
        return self._post_raw(endpoint, payload)

    # ------------ Pedidos de Compra ------------

    def incluir_pedido_compra(self, pedido: Dict[str, Any]) -> Dict[str, Any]:
        return self._call("produtos/pedidocompra/", "IncluirPedCompra", pedido)

    def consultar_pedido_compra(self, chave: Dict[str, Any]) -> Dict[str, Any]:
        # chave exemplo: {"nCodPed": 123} ou {"cNumero": "..."}
        return self._call("produtos/pedidocompra/", "ConsultarPedCompra", chave)

    # ------------ Recebimentos (notas de compra) ------------

    def listar_recebimentos(
        self,
        pagina: int = 1,
        registros_por_pagina: int = 50,
        filtros: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "nPagina": pagina,
            "nRegPorPagina": registros_por_pagina,
        }
        if filtros:
            params.update(filtros)
        return self._call("produtos/recebimentonfe/", "ListarRecebimentos", params)

    # ------------ Contas a Pagar ------------

    def incluir_conta_pagar(self, conta: Dict[str, Any]) -> Dict[str, Any]:
        return self._call("financas/contapagar/", "IncluirContaPagar", conta)

    def consultar_conta_pagar(self, codigo_lancamento: int) -> Dict[str, Any]:
        return self._call(
            "financas/contapagar/",
            "ConsultarContaPagar",
            {"nCodTitulo": codigo_lancamento},
        )

    # ------------ Anexos genéricos ------------

    def listar_anexos(
        self,
        c_tabela: str,
        n_id: int,
        pagina: int = 1,
        limite: int = 50,
    ) -> List[Dict[str, Any]]:
        params = {
            "nPagina": pagina,
            "nRegPorPagina": limite,
            "cTabela": c_tabela,
            "nId": n_id,
        }
        data = self._call("geral/anexo/", "ListarAnexo", params)
        # doc nova usa "listaAnexos"
        return data.get("listaAnexos", []) or data.get("anexos", [])

    def obter_anexo(
        self,
        c_tabela: str,
        n_id: int,
        n_id_anexo: Optional[int] = None,
        c_nome_arquivo: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "cTabela": c_tabela,
            "nId": n_id,
        }
        if n_id_anexo is not None:
            params["nIdAnexo"] = n_id_anexo
        if c_nome_arquivo:
            params["cNomeArquivo"] = c_nome_arquivo
        return self._call("geral/anexo/", "ObterAnexo", params)

    def incluir_anexo(
        self,
        c_tabela: str,
        n_id: int,
        nome_arquivo: str,
        arquivo_base64: str,
        descricao: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "cTabela": c_tabela,
            "nId": n_id,
            "cNomeArquivo": nome_arquivo,
            "cArquivo": arquivo_base64,
        }
        if descricao:
            params["cDescricao"] = descricao
        return self._call("geral/anexo/", "IncluirAnexo", params)

    def copiar_anexo(
        self,
        origem_tabela: str,
        origem_id: int,
        destino_tabela: str,
        destino_id: int,
        anexo_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        n_id_anexo = anexo_info.get("nIdAnexo")
        nome_arquivo = anexo_info.get("cNomeArquivo")

        detalhe = self.obter_anexo(
            c_tabela=origem_tabela,
            n_id=origem_id,
            n_id_anexo=n_id_anexo,
        )

        conteudo_b64 = detalhe.get("cArquivo")
        link = detalhe.get("cLinkDownload")

        if not conteudo_b64 and link:
            resp = requests.get(link, timeout=60)
            resp.raise_for_status()
            conteudo_b64 = base64.b64encode(resp.content).decode()

        if not conteudo_b64:
            raise OmieAPIException("Não foi possível obter conteúdo do anexo na Omie.")

        return self.incluir_anexo(
            c_tabela=destino_tabela,
            n_id=destino_id,
            nome_arquivo=nome_arquivo,
            arquivo_base64=conteudo_b64,
        )

    # ------------ RF-002: Encerramento Pedido (mantido) ------------

    def encerrar_pedido_compra(
        self,
        numero_pedido: str,
        codigo_item: Optional[str] = None,
    ) -> Dict[str, Any]:
        status_val = (self.po_close_status or "Encerrado").strip()
        params: Dict[str, Any] = {
            "cNumero": numero_pedido,
            "cStatus": status_val,
        }
        if codigo_item:
            params["cCodItem"] = codigo_item

        return self._call(self.po_close_endpoint, self.po_close_call, params)
