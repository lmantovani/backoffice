# omie_api/client.py

import base64
import logging
import time
import random
from decimal import Decimal
from typing import Any, Dict, List, Optional

import requests
from decouple import config

logger = logging.getLogger(__name__)


class OmieAPIException(Exception):
    def __init__(self, message: str, *, status_code: Optional[int] = None, retry_after: Optional[float] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.retry_after = retry_after

    def __str__(self) -> str:
        return self.message


def ensure_json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: ensure_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [ensure_json_safe(v) for v in value]
    return value


class OmieAPIClient:
    def __init__(self):
        self.app_key = config("OMIE_APP_KEY")
        self.app_secret = config("OMIE_APP_SECRET")
        self.base_url = config(
            "OMIE_API_BASE_URL",
            default="https://app.omie.com.br/api/v1/",
        )

        self.max_retries = config("OMIE_MAX_RETRIES", default=3, cast=int)
        self.retry_backoff = config("OMIE_RETRY_BACKOFF_SECONDS", default=1.0, cast=float)
        self.retry_jitter_ms = config("OMIE_RETRY_JITTER_MS", default=250, cast=int)

        # Config RF-002 (encerramento pedido)
        self.po_close_status = config("OMIE_PO_CLOSE_STATUS", default="Encerrado")
        self.po_close_call = config("OMIE_PO_CLOSE_CALL", default="AlterarPedidoCompra")
        self.po_close_endpoint = config(
            "OMIE_PO_CLOSE_ENDPOINT",
            default="produtos/pedidocompra/",
        )

        self.attach_zip_before_base64 = config("OMIE_ATTACH_ZIP_BEFORE_BASE64", default=True, cast=bool)
        self.min_interval_seconds = config("OMIE_MIN_INTERVAL_SECONDS", default=0.2, cast=float)

    _last_call_mono: float | None = None
    try:
        import threading as _threading
        _throttle_lock = _threading.Lock()
    except Exception:
        _throttle_lock = None

    @classmethod
    def from_settings(cls) -> "OmieAPIClient":
        return cls()

    def _post_raw(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        safe_payload = ensure_json_safe(payload)
        retriable_status = {429, 500, 502, 503, 504}

        attempt = 0
        while True:
            try:
                if self.min_interval_seconds and self.min_interval_seconds > 0:
                    lock = getattr(self, "_throttle_lock", None)
                    if lock:
                        with lock:
                            now = time.monotonic()
                            last = OmieAPIClient._last_call_mono
                            if last is not None:
                                elapsed = now - last
                                if elapsed < self.min_interval_seconds:
                                    sleep_s = self.min_interval_seconds - elapsed
                                    time.sleep(sleep_s)
                                    now = time.monotonic()
                            OmieAPIClient._last_call_mono = now
            except Exception:
                pass
            try:
                resp = requests.post(url, json=safe_payload, timeout=60)
            except requests.RequestException as exc:
                if attempt < self.max_retries:
                    attempt += 1
                    backoff = self.retry_backoff * (2 ** (attempt - 1))
                    jitter = random.uniform(0, self.retry_jitter_ms / 1000.0)
                    sleep_s = backoff + jitter
                    logger.warning(
                        "Falha na requisição Omie (tentativa %s/%s): %s. Retentando em %.2fs...",
                        attempt,
                        self.max_retries,
                        exc,
                        sleep_s,
                    )
                    time.sleep(sleep_s)
                    continue
                logger.error("Erro HTTP Omie (requisição): %s", exc)
                raise OmieAPIException(f"Erro HTTP ao chamar Omie: {exc}") from exc

            resp_text = resp.text
            data = None
            try:
                data = resp.json()
            except ValueError:
                logger.warning(
                    "Resposta não JSON da Omie (status=%s, endpoint=%s): %s",
                    resp.status_code,
                    endpoint,
                    resp_text,
                )
            if resp.status_code >= 400:
                if resp.status_code in retriable_status and attempt < self.max_retries:
                    attempt += 1
                    retry_after_hdr = resp.headers.get("Retry-After")
                    sleep_s: float | None = None
                    if retry_after_hdr:
                        try:
                            sleep_s = float(retry_after_hdr)
                        except ValueError:
                            sleep_s = None
                    if sleep_s is None:
                        backoff = self.retry_backoff * (2 ** (attempt - 1))
                        jitter = random.uniform(0, self.retry_jitter_ms / 1000.0)
                        sleep_s = backoff + jitter
                    logger.warning(
                        "HTTP %s da Omie (endpoint=%s). Tentativa %s/%s. Aguardando %.2fs para retentar...",
                        resp.status_code,
                        endpoint,
                        attempt,
                        self.max_retries,
                        sleep_s,
                    )
                    time.sleep(sleep_s)
                    continue

                fault = None
                if isinstance(data, dict):
                    fault = (
                        data.get("faultstring")
                        or data.get("faultcode")
                        or data.get("mensagem")
                        or data.get("descricao")
                    )
                logger.error(
                    "Erro HTTP Omie: status=%s endpoint=%s response=%s",
                    resp.status_code,
                    endpoint,
                    data or resp_text,
                )
                reason = resp.reason or "Erro"
                message = f"Erro HTTP ao chamar Omie: {resp.status_code} {reason}"
                if fault:
                    message += f" | Detalhe: {fault}"
                retry_after_final: Optional[float] = None
                try:
                    ra_hdr_val = resp.headers.get("Retry-After")
                    if ra_hdr_val is not None:
                        retry_after_final = float(ra_hdr_val)
                except Exception:
                    retry_after_final = None
                raise OmieAPIException(message, status_code=resp.status_code, retry_after=retry_after_final)

            if isinstance(data, dict) and "faultstring" in data:
                logger.error("Erro Omie: %s", data)
                raise OmieAPIException(data["faultstring"]) 

            if data is None:
                return {}
            return data

    def _call(self, endpoint: str, call: str, params: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "call": call,
            "app_key": self.app_key,
            "app_secret": self.app_secret,
            "param": [params],
        }
        logger.info("Omie API call=%s endpoint=%s", call, endpoint)
        if call == "IncluirPedCompra":
            try:
                logger.debug("Omie payload (param) IncluirPedCompra: %s", ensure_json_safe({"param": [params]}))
            except Exception:
                pass
        return self._post_raw(endpoint, payload)

    # ------------ Pedidos de Compra ------------

    def incluir_pedido_compra(self, pedido: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(
            "Omie IncluirPedCompra: enviando com formato com_pedido_incluir_request (sem wrapper)"
        )
        return self._call(
            endpoint="produtos/pedidocompra/",
            call="IncluirPedCompra",
            params=pedido,
        )

    def consultar_pedido_compra(self, chave: Dict[str, Any]) -> Dict[str, Any]:
        return self._call("produtos/pedidocompra/", "ConsultarPedCompra", chave)

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
            "nCodigo": n_id,
        }
        data = self._call("geral/anexo/", "ListarAnexo", params)
        if not isinstance(data, dict) or ("listaAnexos" not in data and "anexos" not in data):
            try:
                fallback = self._call("geral/anexo/", "ListarAnexos", params)
                if isinstance(fallback, dict) and ("listaAnexos" in fallback or "anexos" in fallback):
                    data = fallback
                    logger.debug("ListarAnexos (plural) usado como fallback com sucesso.")
            except Exception:
                logger.debug("Falha ao usar fallback ListarAnexos; mantendo resposta de ListarAnexo.")
        logger.debug(
            "Resposta ListarAnexo cTabela=%s nId=%s: %s",
            c_tabela,
            n_id,
            data,
        )
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
            # Identificador do documento
            "nCodigo": n_id,
        }
        if n_id_anexo is not None:
            params["nIdAnexo"] = n_id_anexo
        if c_nome_arquivo:
            params["cNomeArquivo"] = c_nome_arquivo
        return self._call("geral/anexo/", "ObterAnexo", params)

    def incluir_anexo(
        self,
        *,
        tabela: str,
        n_id: int,
        nome_arquivo: str,
        tipo_arquivo: Optional[str] = None,
        arquivo_bytes: bytes,
        cod_int_anexo: Optional[str] = None,
        descricao: Optional[str] = None,  # mantido apenas por compatibilidade; ignorado
    ) -> Dict[str, Any]:
        """
        Envia um anexo para a Omie (DocumentoAnexo.IncluirAnexo).
        docIncluirAnexoRequest:
          - cTabela      -> "pedido-compra", "nota-entrada", "conta-pagar" etc.
          - nId          -> ID do documento (nCodPed, nIdTitulo, etc.)
          - cNomeArquivo -> nome do arquivo
          - cTipoArquivo -> "PDF", "XML"...
          - cArquivo     -> arquivo (zipado ou não) em base64
          - cMd5         -> MD5 do conteúdo enviado em cArquivo
        Observação: a Omie não aceita a tag cDescricao neste contrato; qualquer tag fora do
        contrato causa erro 500. Portanto, mesmo que seja informado o parâmetro `descricao`,
        ele será ignorado e NÃO será enviado no payload.
        """
        if not tabela or not n_id or not nome_arquivo or arquivo_bytes is None:
            raise OmieAPIException("Parâmetros obrigatórios ausentes para incluir_anexo.")

        # Prepara conteúdo: por padrão, compacta em ZIP e envia o ZIP em base64 (conforme doc Omie)
        raw = arquivo_bytes
        if self.attach_zip_before_base64:
            try:
                import io
                import zipfile
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                    arcname = nome_arquivo or "anexo"
                    zf.writestr(arcname, arquivo_bytes)
                raw = buf.getvalue()
            except Exception as _zip_exc:
                # Se falhar a compactação, faz fallback para enviar o conteúdo bruto
                logger.warning("Falha ao compactar arquivo antes do envio para Omie: %s. Enviando sem ZIP.", _zip_exc)
                raw = arquivo_bytes

        # Base64 do conteúdo e MD5 do EXATO conteúdo enviado em cArquivo (string base64)
        # Observação: a Omie valida o MD5 do campo cArquivo (string base64),
        # e não do binário bruto. Por isso calculamos sobre a string base64.
        b64_str = base64.b64encode(raw).decode("ascii")
        import hashlib as _hashlib  # import local para evitar topo com alias
        md5_hex = _hashlib.md5(b64_str.encode("ascii")).hexdigest()

        # Inferência de tipo do arquivo se não informado
        tipo_map = {
            "pdf": "PDF",
            "xml": "XML",
            "jpg": "JPG",
            "jpeg": "JPG",
            "png": "PNG",
            "txt": "TXT",
        }
        if not tipo_arquivo:
            ext = (nome_arquivo.rsplit(".", 1)[-1] or "").lower() if "." in (nome_arquivo or "") else ""
            tipo_arquivo = tipo_map.get(ext, "OUTROS")

        params: Dict[str, Any] = {
            "cTabela": tabela,
            # Algumas contas da Omie esperam a chave 'nId' no contrato do IncluirAnexo
            # (docIncluirAnexoRequest). Para compatibilidade, enviamos 'nId' aqui.
            "nId": n_id,
            "cNomeArquivo": nome_arquivo,
            "cArquivo": b64_str,
            "cMd5": md5_hex,
        }
        # cTipoArquivo é obrigatório segundo doc; sempre enviar
        params["cTipoArquivo"] = tipo_arquivo
        if cod_int_anexo:
            params["cCodIntAnexo"] = cod_int_anexo
        # NUNCA enviar cDescricao: fora do contrato da Omie

        logger.info("Omie API call=IncluirAnexo endpoint=geral/anexo/")
        resp = self._call("geral/anexo/", "IncluirAnexo", params)
        logger.debug("Resposta IncluirAnexo: %s", resp)
        return resp

    def incluir_anexo_base64(
        self,
        *,
        tabela: str,
        n_id: int,
        nome_arquivo: str,
        arquivo_base64: str,
        tipo_arquivo: Optional[str] = None,
        cod_int_anexo: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Variante que recebe o conteúdo já em base64 e calcula o MD5 a partir
        dessa string (que é exatamente o que a Omie valida em cArquivo).
        """
        if not tabela or not n_id or not nome_arquivo or not arquivo_base64:
            raise OmieAPIException("Parâmetros obrigatórios ausentes para incluir_anexo_base64.")

        try:
            import hashlib as _hashlib
            md5_hex = _hashlib.md5(str(arquivo_base64).encode("ascii")).hexdigest()
        except Exception as exc:
            raise OmieAPIException(f"Falha ao calcular MD5 do conteúdo base64: {exc}") from exc

        # Inferência de tipo quando possível
        if not tipo_arquivo:
            tipo_map = {
                "pdf": "PDF",
                "xml": "XML",
                "jpg": "JPG",
                "jpeg": "JPG",
                "png": "PNG",
                "txt": "TXT",
            }
            ext = (nome_arquivo.rsplit(".", 1)[-1] or "").lower() if "." in (nome_arquivo or "") else ""
            tipo_arquivo = tipo_map.get(ext, "OUTROS")

        params: Dict[str, Any] = {
            "cTabela": tabela,
            # Compat: enviar 'nId' conforme contrato aceito pelo endpoint IncluirAnexo
            "nId": n_id,
            "cNomeArquivo": nome_arquivo,
            "cArquivo": str(arquivo_base64),
            "cMd5": md5_hex,
        }
        # Sempre enviar tipo
        params["cTipoArquivo"] = tipo_arquivo
        if cod_int_anexo:
            params["cCodIntAnexo"] = cod_int_anexo

        logger.info("Omie API call=IncluirAnexo endpoint=geral/anexo/")
        resp = self._call("geral/anexo/", "IncluirAnexo", params)
        logger.debug("Resposta IncluirAnexo: %s", resp)
        return resp

    def incluir_anexo_dict(self, anexo: Dict[str, Any]) -> Dict[str, Any]:
        """
        Inclui anexo aceitando diretamente o objeto do anexo conforme a documentação Omie.

        Exemplo de `anexo`:
        {
          "cTabela": "pedido-compra",
          "nId": 10408496656,
          "cDescricao": "...",
          "cNomeArquivo": "arquivo.pdf",
          "cArquivoBase64": "...",
          "cMd5": "md5hex..."
        }

        Observação: o objeto é enviado diretamente dentro do array `param` (sem wrapper adicional).
        """
        logger.info("Omie API call=IncluirAnexo endpoint=geral/anexo/")
        # Se vier com cArquivoBase64 (variante nova), converte para cArquivo antes de enviar
        payload = dict(anexo)
        # Remover cDescricao se vier indevidamente
        if "cDescricao" in payload:
            payload.pop("cDescricao", None)
        # Normaliza o identificador para o contrato efetivamente aceito pelo IncluirAnexo.
        # Se vier "nCodigo" (de integrações que usam essa chave), convertemos para "nId".
        if "nCodigo" in payload and "nId" not in payload:
            payload["nId"] = payload.pop("nCodigo")
        if "cArquivo" not in payload and "cArquivoBase64" in payload:
            payload["cArquivo"] = payload.pop("cArquivoBase64")
        # Sempre recalcula o MD5 a partir do EXATO conteúdo enviado em cArquivo (string base64),
        # sobrescrevendo qualquer cMd5 fornecido externamente, para evitar divergências.
        if "cArquivo" in payload:
            try:
                import hashlib as _hashlib
                b64_str = str(payload["cArquivo"])  # garantir string
                payload["cMd5"] = _hashlib.md5(b64_str.encode("ascii")).hexdigest()
            except Exception:
                payload.pop("cMd5", None)
        # _call cuidará de empacotar como {"param": [payload]}
        return self._call("geral/anexo/", "IncluirAnexo", payload)

    # Backward-compatibility helper: aceita base64 diretamente (legado)
    def incluir_anexo_base64(
        self,
        *,
        tabela: Optional[str] = None,
        n_id: Optional[int] = None,
        nome_arquivo: Optional[str] = None,
        arquivo_base64: Optional[str] = None,
        descricao: Optional[str] = None,  # mantido por compatibilidade; ignorado
        c_tabela: Optional[str] = None,
        c_md5: Optional[str] = None,
        tipo_arquivo: Optional[str] = None,
        cod_int_anexo: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        [DEPRECATED] Use incluir_anexo(arquivo_bytes=...) em novos fluxos.
        Mantido para compatibilidade com chamadas antigas que já possuem base64 pronto.
        """
        tabela_final = c_tabela or tabela
        if tabela_final is None or n_id is None or not nome_arquivo or not arquivo_base64:
            raise OmieAPIException("Parâmetros obrigatórios ausentes para incluir_anexo_base64.")

        raw = base64.b64decode(arquivo_base64)
        # Se vier md5 pronto, usa; caso contrário calcula
        import hashlib as _hashlib
        md5_hex = c_md5 or _hashlib.md5(raw).hexdigest()

        params: Dict[str, Any] = {
            "cTabela": tabela_final,
            "nId": n_id,
            "cNomeArquivo": nome_arquivo,
            "cArquivo": arquivo_base64,
            "cMd5": md5_hex,
        }
        # Nunca enviar cDescricao no payload
        if tipo_arquivo:
            params["cTipoArquivo"] = tipo_arquivo
        if cod_int_anexo:
            params["cCodIntAnexo"] = cod_int_anexo

        logger.info("Omie API call=IncluirAnexo endpoint=geral/anexo/")
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

        # Algumas respostas usam cArquivoBase64, outras cArquivo
        conteudo_b64 = detalhe.get("cArquivoBase64") or detalhe.get("cArquivo")
        link = detalhe.get("cLinkDownload")

        if not conteudo_b64 and link:
            resp = requests.get(link, timeout=60)
            resp.raise_for_status()
            conteudo_b64 = base64.b64encode(resp.content).decode()

        if not conteudo_b64:
            raise OmieAPIException("Não foi possível obter conteúdo do anexo na Omie.")

        # Usa caminho compatível com base64 pronto
        return self.incluir_anexo_base64(
            tabela=destino_tabela,
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

    # ------------ Catálogos auxiliares ------------

    def listar_categorias_compra(self, pagina: int = 1, registros_por_pagina: int = 200) -> Dict[str, Any]:
        params = {
            "pagina": pagina,
            "registros_por_pagina": registros_por_pagina,
        }
        return self._call("financas/categorias/", "ListarCategorias", params)

    def listar_compradores(self, pagina: int = 1, registros_por_pagina: int = 200) -> Dict[str, Any]:
        params = {
            "pagina": pagina,
            "registros_por_pagina": registros_por_pagina,
        }
        return self._call("produtos/compradores/", "ListarCompradores", params)
