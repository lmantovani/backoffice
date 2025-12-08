import base64
import hashlib
import copy
import logging
import requests
import uuid
from decimal import Decimal, InvalidOperation
from datetime import datetime
from django.conf import settings

from django.db import transaction

from omie_api.client import OmieAPIClient, OmieAPIException, ensure_json_safe
from attachments.models import AttachmentSyncLog
from .models import (
    PurchaseOrderClosureLog,
    PurchaseOrderIntegration,
    PurchaseOrderFinanceMap,
)

logger = logging.getLogger(__name__)

MONETARY_HEADER_FIELDS = {"nValorTotal", "nValorMercadoria", "nValorDesconto", "nValorFrete"}
MONETARY_ITEM_FIELDS = {"nValUnitario", "nValTotal"}
MONETARY_INSTALLMENT_FIELDS = {"nValorParcela"}
INT_HEADER_FIELDS = {"nCodFor", "nCodCompr", "nCodCC", "nCodProj", "nQtdeParc"}


def _decimal_to_string(value) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    try:
        return format(Decimal(str(value)), "f")
    except (InvalidOperation, TypeError, ValueError):
        return str(value)


def _normalize_decimal(value, *, monetary: bool):
    if value is None:
        return None
    if monetary:
        return _decimal_to_string(value)
    if isinstance(value, Decimal):
        return float(value)
    return value


def _coerce_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _format_date_ddmmyyyy(value: str | None) -> str:
    """Converte datas para formato dd/MM/yyyy.
    Aceita formatos comuns (yyyy-MM-dd, dd/MM/yyyy, yyyy/MM/dd, dd-MM-yyyy) ou retorna string original.
    """
    if not value:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    # já está no formato esperado
    try:
        # valida rapidamente dd/MM/yyyy
        dt = datetime.strptime(s, "%d/%m/%Y")
        return dt.strftime("%d/%m/%Y")
    except Exception:
        pass
    # tenta alguns formatos comuns
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%m/%d/%Y", "%d.%m.%Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%d/%m/%Y")
        except Exception:
            continue
    # não conseguiu converter, retorna como veio
    return s


def prepare_purchase_order_payload(pedido_data: dict) -> dict:
    """Monta o payload do pedido no formato esperado pela Omie (IncluirPedCompra).

    Entrada esperada (conforme serializers):
      {
        "cabecalho": {
          "cCodIntPed": str?,
          "codigo_cliente_fornecedor": int | str,
          "dDtPrevisao": "dd/MM/yyyy",
          "nQtdeParcelas": int,
          "observacao": str?,
          "codigo_categoria": str?,
          "cCodComprador": str | int?,
          "nValorFrete": Decimal? (opcional)
        },
        "det": [ { itens... } ],
        "informacoes_adicionais": { "observacao_interna": str? }?
      }

    Saída: estrutura com chaves cabecalho_incluir, frete_incluir, departamentos_incluir, produtos_incluir.
    """
    data = copy.deepcopy(pedido_data) or {}
    cab = data.get("cabecalho", {}) or {}
    itens = data.get("det") or []
    info_add = data.get("informacoes_adicionais") or {}

    c_cod_int_ped = cab.get("cCodIntPed") or ""
    data_previsao = _format_date_ddmmyyyy(cab.get("dDtPrevisao") or cab.get("dDataPrevisao") or "")
    n_parcelas = cab.get("nQtdeParcelas") or cab.get("nQtdeParc") or 1
    cod_fornecedor = cab.get("codigo_cliente_fornecedor") or cab.get("nCodFor") or ""
    cod_categoria = cab.get("codigo_categoria") or cab.get("cCodCateg") or ""
    cod_comprador = cab.get("cCodComprador") or cab.get("nCodCompr") or ""
    observacao = cab.get("observacao") or cab.get("cObs") or ""
    observacao_interna = info_add.get("observacao_interna") or cab.get("cObsInt") or ""
    valor_frete = cab.get("nValorFrete")

    # Header conforme exemplo do usuário
    # Apenas campos do contrato conhecidos/essenciais. Removemos parcelas e outros não utilizados.
    cabecalho_incluir = {
        "cCodIntPed": c_cod_int_ped,
        "dDtPrevisao": data_previsao,
        # nCodFor deve ser string
        "nCodFor": str(cod_fornecedor) if cod_fornecedor not in (None, "") else "",
        "cCodCateg": str(cod_categoria) if cod_categoria not in (None, "") else "",
        # Comprador pode ser numérico ou string conforme cadastro
        "nCodCompr": int(cod_comprador) if str(cod_comprador).isdigit() else (cod_comprador or 0),
        "cObs": observacao,
        "cObsInt": observacao_interna or "",
    }

    # Frete
    # Mínimo necessário para frete no contrato: enviar somente nValFrete quando houver.
    frete_incluir = {
        "nValFrete": float(valor_frete) if valor_frete not in (None, "") else 0.0,
    }

    # Produtos (itens)
    produtos_incluir: list[dict] = []
    for idx, item in enumerate(itens, start=1):
        qtd = item.get("nQtdeItem")
        val_unit = item.get("nValUnitario")
        desconto = item.get("nPercentualDesconto") or 0
        produto = {
            "cCodIntItem": item.get("cCodIntItem") or f"ITEM{idx:03d}",
            # nCodProd exigido pelo Omie — enviar como string
            "nCodProd": str(item.get("codigo_produto") or ""),
            "cDescricao": item.get("descricao") or "",
            "cUnidade": item.get("unidade") or "",
            "nQtde": float(qtd) if qtd not in (None, "") else 0.0,
            "nValUnit": float(val_unit) if val_unit not in (None, "") else 0.0,
        }
        if desconto not in (None, ""):
            produto["nDesconto"] = float(desconto)
        produtos_incluir.append(produto)

    payload = {
        "cabecalho_incluir": cabecalho_incluir,
        "frete_incluir": frete_incluir,
        # se não estiver usando departamentos, pode mandar lista vazia
        "departamentos_incluir": [],
        "produtos_incluir": produtos_incluir,
    }

    return payload


class OmieClient:
    BASE_URL = "https://app.omie.com.br/api/v1"

    @classmethod
    def call(cls, endpoint: str, method: str, body: dict):
        payload = {
            "call": method,
            "app_key": settings.OMIE_APP_KEY,
            "app_secret": settings.OMIE_APP_SECRET,
            "param": [body],
        }
        url = f"{cls.BASE_URL}{endpoint}"
        safe_payload = ensure_json_safe(payload)
        resp = requests.post(url, json=safe_payload, timeout=30)

        # tenta converter para JSON (a Omie normalmente sempre responde JSON)
        try:
            data = resp.json()
        except ValueError:
            logger.error(
                "Resposta não-JSON da Omie (status=%s): %s",
                resp.status_code,
                resp.text,
            )
            # ainda deixa estourar o erro HTTP para você ver em dev
            resp.raise_for_status()
            return {}

        # se vier HTTP 4xx/5xx, tenta extrair mensagem amigável do JSON
        if resp.status_code >= 400:
            msg = (
                data.get("faultstring")
                or data.get("mensagem")
                or data.get("descricao")
                or resp.reason
            )
            logger.error(
                "Erro HTTP na Omie (status=%s): %s | payload=%s",
                resp.status_code,
                msg,
                data,
            )
            # usa tua exception padrão do client Omie
            raise OmieAPIException(msg)

        # alguns métodos da Omie devolvem erro lógico mesmo com 200
        if isinstance(data, dict) and data.get("faultstring"):
            msg = data["faultstring"]
            logger.error("Erro lógico na Omie: %s | payload=%s", msg, data)
            raise OmieAPIException(msg)

        return data



class SupplierService:
    """
    Consulta fornecedores no Omie usando ListarClientes.
    Para evitar erro de estrutura (PESQUISA), pegamos a lista "crua"
    e filtramos em Python pelo termo digitado.
    """

    @staticmethod
    def list_suppliers(search: str | None = None, page: int = 1, per_page: int = 200) -> list[dict]:
        """Lista fornecedores direto na Omie (versão simples, sem cache/retentativas).

        - Não utiliza o parâmetro "pesquisa" na Omie (filtramos em memória).
        - Usa o cliente simples OmieClient.call sem camadas extras.
        """
        body = {
            "pagina": page,
            "registros_por_pagina": per_page,
            "apenas_importado_api": "N",
        }

        data = OmieClient.call(
            endpoint="/geral/clientes/",
            method="ListarClientes",
            body=body,
        )

        clientes = data.get("clientes_cadastro", []) or []
        resultados: list[dict] = []

        termo = (search or "").strip().lower()

        for cli in clientes:
            supplier = {
                "id": cli.get("codigo_cliente_omie"),
                "nome": cli.get("razao_social") or cli.get("nome_fantasia"),
                "cnpj_cpf": cli.get("cnpj_cpf"),
            }

            # se não tem termo de busca, devolve todos
            if not termo:
                resultados.append(supplier)
                continue

            # filtro simples em Python: código, nome, CNPJ/CPF
            texto = " ".join([
                str(supplier.get("id") or ""),
                supplier.get("nome") or "",
                supplier.get("cnpj_cpf") or "",
            ]).lower()

            if termo in texto:
                resultados.append(supplier)

        return resultados



class PurchaseOrderClosureService:
    """Orquestra o encerramento de pedidos no Omie e mantém o log local."""

    def __init__(self, omie_client: OmieAPIClient | None = None):
        self.omie = omie_client or OmieAPIClient.from_settings()

    def encerrar_pedido_automaticamente(
        self,
        numero_pedido: str,
        item_pedido: str | None,
        numero_nf_servico: str,
        id_nf_servico: int,
    ) -> PurchaseOrderClosureLog:
        log = PurchaseOrderClosureLog.objects.create(
            numero_pedido=numero_pedido,
            item_pedido=item_pedido,
            numero_nf_servico=numero_nf_servico,
            id_nf_servico=id_nf_servico,
        )
        return self._processar_log(log)

    def reprocessar_falhas(self) -> list[PurchaseOrderClosureLog]:
        candidatos = PurchaseOrderClosureLog.objects.filter(status__in=["failed", "pending"]).order_by("-updated_at")
        resultados: list[PurchaseOrderClosureLog] = []
        for log in candidatos:
            if not log.pode_retentar:
                continue
            try:
                resultados.append(self._processar_log(log))
            except Exception:
                # exceções já foram logadas em _processar_log; segue reprocessando os demais
                continue
        return resultados

    def _processar_log(self, log: PurchaseOrderClosureLog) -> PurchaseOrderClosureLog:
        log.mark_as_processing()
        try:
            consulta = self.omie.consultar_pedido_compra({"cNumero": log.numero_pedido})
            kwargs = {"numero_pedido": log.numero_pedido}
            if log.item_pedido:
                kwargs["codigo_item"] = log.item_pedido
            encerramento = self.omie.encerrar_pedido_compra(**kwargs)
            log.mark_as_success(
                detalhes={
                    "consulta": consulta,
                    "encerramento": encerramento,
                }
            )
        except Exception as exc:
            logger.exception("Falha ao encerrar pedido %s", log.numero_pedido)
            log.mark_as_failed(str(exc))
            raise
        return log



class FullFlowPurchaseOrderService:
    """
    Fluxo completo via BackOffice:
    - cria pedido de compra na Omie
    - envia anexos
    - quando finalizado, cria conta a pagar
    - copia anexos do pedido para o contas a pagar
    """

    def __init__(self, omie_client: OmieAPIClient | None = None):
        self.omie = omie_client or OmieAPIClient.from_settings()

    @transaction.atomic
    def criar_pedido_com_anexos(self, pedido_data: dict, arquivos) -> PurchaseOrderIntegration:
        cabecalho = pedido_data.get("cabecalho", {})
        if not cabecalho.get("cCodIntPed"):
            cabecalho["cCodIntPed"] = f"PO-{uuid.uuid4().hex[:12]}"
        pedido_data = {
            **pedido_data,
            "cabecalho": cabecalho,
        }

        pedido_payload = prepare_purchase_order_payload(pedido_data)
        logger.debug("Payload IncluirPedCompra: %s", pedido_payload)

        resp = self.omie.incluir_pedido_compra(pedido_payload)
        logger.debug("Resposta IncluirPedCompra: %s", resp)
        ncodped = resp.get("nCodPed")
        if not ncodped:
            raise OmieAPIException(f"Resposta Omie sem nCodPed: {resp}")

        po = PurchaseOrderIntegration.objects.create(
            cod_int_pedido=cabecalho.get("cCodIntPed"),
            ncodped_omie=ncodped,
            origem="backoffice",
            metodo_criacao="sistema",
        )

        for arquivo in arquivos:
            # lê bytes do arquivo
            conteudo = arquivo.read()
            # volta o ponteiro caso o chamador precise reler depois
            try:
                arquivo.seek(0)
            except Exception:
                pass

            # infere tipo do arquivo (opcional)
            nome = getattr(arquivo, "name", "") or ""
            ext = (nome.rsplit(".", 1)[-1] or "").lower() if "." in nome else ""
            tipo_arquivo = "PDF" if ext == "pdf" else None

            # envia anexo conforme orientação da Omie (cliente calcula base64 + md5)
            self.omie.incluir_anexo(
                tabela="pedido-compra",
                n_id=ncodped,
                nome_arquivo=nome or "anexo",
                tipo_arquivo=tipo_arquivo,
                arquivo_bytes=conteudo,
                descricao=nome or None,
            )
            AttachmentSyncLog.objects.create(
                origem_tabela="pedido-compra",
                origem_id=ncodped,
                destino_tabela="pedido-compra",
                destino_id=ncodped,
                metodo="sistema_full_flow",
                nome_arquivo=arquivo.name,
                status="success",
            )

        return po

    def processar_pedido_para_financeiro(self, po: PurchaseOrderIntegration) -> PurchaseOrderFinanceMap | None:
        dados = self.omie.consultar_pedido_compra({"nCodPed": po.ncodped_omie})

        if not self._pedido_finalizado(dados):
            logger.info("Pedido %s ainda não finalizado.", po.ncodped_omie)
            return None

        if hasattr(po, "finance_map"):
            logger.info("Financeiro já existe para pedido %s.", po.ncodped_omie)
            return po.finance_map

        conta_payload = self._montar_conta_pagar(dados, po.cod_int_pedido)
        resp = self.omie.incluir_conta_pagar(conta_payload)
        cod_lanc = resp.get("codigo_lancamento_omie")
        if not cod_lanc:
            raise OmieAPIException(f"Resposta Omie sem codigo_lancamento_omie: {resp}")

        fmap = PurchaseOrderFinanceMap.objects.create(
            purchase_order=po,
            codigo_lancamento_omie=cod_lanc,
            metodo_criacao="sistema_full_flow",
            anexos_sincronizados=False,
        )

        self._replicar_anexos_pedido_para_financeiro(po, fmap)

        return fmap

    # ---------- helpers internos ----------

    def _pedido_finalizado(self, dados_pedido: dict) -> bool:
        status = (dados_pedido or {}).get("cStatus", "").lower()
        return status in ("fechado", "encerrado")  # ajuste se precisar

    def _montar_conta_pagar(self, dados_pedido: dict, cod_int_pedido: str | None) -> dict:
        total = dados_pedido.get("nValorTotal", 0)
        fornecedor = dados_pedido.get("codigo_cliente_fornecedor")

        return {
            "codigo_lancamento_integracao": f"PO-{cod_int_pedido or dados_pedido.get('nCodPed')}",
            "codigo_cliente_fornecedor": fornecedor,
            "valor_documento": total,
            "data_vencimento": dados_pedido.get("dDataPrevisao", dados_pedido.get("dDataEmissao")),
            "numero_documento": str(dados_pedido.get("nCodPed")),
            # completar depois com os campos obrigatórios da API
        }

    def _replicar_anexos_pedido_para_financeiro(
        self,
        po: PurchaseOrderIntegration,
        fmap: PurchaseOrderFinanceMap,
    ):
        anexos = self.omie.listar_anexos("pedido-compra", po.ncodped_omie)

        for a in anexos:
            try:
                self.omie.copiar_anexo(
                    origem_tabela="pedido-compra",
                    origem_id=po.ncodped_omie,
                    destino_tabela="conta-pagar",
                    destino_id=fmap.codigo_lancamento_omie,
                    anexo_info=a,
                )
                AttachmentSyncLog.objects.create(
                    origem_tabela="pedido-compra",
                    origem_id=po.ncodped_omie,
                    destino_tabela="conta-pagar",
                    destino_id=fmap.codigo_lancamento_omie,
                    metodo="sistema_full_flow",
                    nome_arquivo=a.get("cNomeArquivo", ""),
                    status="success",
                )
            except Exception as exc:
                logger.exception("Falha ao copiar anexo do pedido %s", po.ncodped_omie)
                fmap.last_error = str(exc)
                fmap.save(update_fields=["last_error"])
                AttachmentSyncLog.objects.create(
                    origem_tabela="pedido-compra",
                    origem_id=po.ncodped_omie,
                    destino_tabela="conta-pagar",
                    destino_id=fmap.codigo_lancamento_omie,
                    metodo="sistema_full_flow",
                    nome_arquivo=a.get("cNomeArquivo", ""),
                    status="failed",
                    mensagem_erro=str(exc),
                )


class PurchaseOrderRobotService:
    """
    Robô que lê dados do Omie e garante:
    - registro dos pedidos criados direto no Omie
    - criação de contas a pagar
    - cópia de anexos (com-recebimento -> conta-pagar)
    """

    def __init__(self, omie_client: OmieAPIClient | None = None):
        self.omie = omie_client or OmieAPIClient.from_settings()

    def processar(self):
        pagina = 1

        while True:
            resp = self.omie.listar_recebimentos(pagina=pagina, registros_por_pagina=50)
            recebimentos = resp.get("recebimentos", []) or resp.get("listaRecebimentos", [])
            if not recebimentos:
                break

            for rec in recebimentos:
                n_cod_ped = rec.get("nCodPedido")
                n_id_receb = rec.get("nIdReceb")
                if not n_cod_ped or not n_id_receb:
                    continue

                po, _ = PurchaseOrderIntegration.objects.get_or_create(
                    ncodped_omie=n_cod_ped,
                    defaults={
                        "origem": "omie",
                        "metodo_criacao": "robo",
                    },
                )

                if hasattr(po, "finance_map"):
                    continue

                conta_payload = {
                    "codigo_lancamento_integracao": f"ROBO-PO-{n_cod_ped}",
                    "codigo_cliente_fornecedor": rec.get("nIdFornecedor")
                    or rec.get("codigo_cliente_fornecedor"),
                    "valor_documento": rec.get("nValorNFe"),
                    "data_vencimento": rec.get("dVencimento") or rec.get("dEmissaoNFe"),
                    "numero_documento": str(n_cod_ped),
                }

                try:
                    resp_cp = self.omie.incluir_conta_pagar(conta_payload)
                    cod_lanc = resp_cp.get("codigo_lancamento_omie")
                    if not cod_lanc:
                        raise OmieAPIException(f"Sem codigo_lancamento_omie: {resp_cp}")

                    fmap = PurchaseOrderFinanceMap.objects.create(
                        purchase_order=po,
                        codigo_lancamento_omie=cod_lanc,
                        metodo_criacao="robo",
                        anexos_sincronizados=False,
                    )

                    self._copiar_anexos_recebimento_para_financeiro(n_id_receb, fmap)

                except Exception as exc:
                    logger.exception(
                        "Erro ao processar pedido %s / recebimento %s",
                        n_cod_ped,
                        n_id_receb,
                    )

            pagina += 1

    def _copiar_anexos_recebimento_para_financeiro(
        self,
        n_id_receb: int,
        fmap: PurchaseOrderFinanceMap,
    ):
        anexos = self.omie.listar_anexos("com-recebimento", n_id_receb)

        for a in anexos:
            try:
                self.omie.copiar_anexo(
                    origem_tabela="com-recebimento",
                    origem_id=n_id_receb,
                    destino_tabela="conta-pagar",
                    destino_id=fmap.codigo_lancamento_omie,
                    anexo_info=a,
                )
                AttachmentSyncLog.objects.create(
                    origem_tabela="com-recebimento",
                    origem_id=n_id_receb,
                    destino_tabela="conta-pagar",
                    destino_id=fmap.codigo_lancamento_omie,
                    metodo="robo",
                    nome_arquivo=a.get("cNomeArquivo", ""),
                    status="success",
                )
            except Exception as exc:
                logger.exception(
                    "Falha ao copiar anexo do recebimento %s",
                    n_id_receb,
                )
                fmap.last_error = str(exc)
                fmap.save(update_fields=["last_error"])
                AttachmentSyncLog.objects.create(
                    origem_tabela="com-recebimento",
                    origem_id=n_id_receb,
                    destino_tabela="conta-pagar",
                    destino_id=fmap.codigo_lancamento_omie,
                    metodo="robo",
                    nome_arquivo=a.get("cNomeArquivo", ""),
                    status="failed",
                    mensagem_erro=str(exc),
                )


class CategoryService:
    @staticmethod
    def list_categories(search: str | None = None, page: int = 1, per_page: int = 200) -> list[dict]:
        data = OmieClient.call(
            endpoint="/geral/categorias/",
            method="ListarCategorias",
            body={"pagina": page, "registros_por_pagina": per_page},
        )
        categorias = (
            data.get("categoria_cadastro", [])
            or data.get("categoriasCadastro", [])
            or data.get("categorias_cadastro", [])
            or []
        )
        termo = (search or "").strip().lower()
        resultados = []
        for cat in categorias:
            registro = {
                "codigo": cat.get("codigo"),
                "descricao": cat.get("descricao") or cat.get("descricao_padrao"),
            }
            if not termo:
                resultados.append(registro)
                continue
            texto = f"{registro['codigo']} {registro['descricao'] or ''}".lower()
            if termo in texto:
                resultados.append(registro)
        return resultados


class BuyerService:
    @staticmethod
    def list_buyers(search: str | None = None, page: int = 1, per_page: int = 200) -> list[dict]:
        try:
            data = OmieClient.call(
                endpoint="/estoque/comprador/",
                method="ListarCompradores",
                body={"pagina": page, "registros_por_pagina": per_page},
            )
        except OmieAPIException as exc:
            mensagem = str(exc)
            if "Não existem registros" in mensagem or "Nenhum registro foi encontrado" in mensagem:
                logger.info("Omie retornou nenhum comprador na página %s.", page)
                return []
            raise

        compradores = (
            data.get("cadastros", [])
            or data.get("compradores_cadastro", [])
            or []
        )
        termo = (search or "").strip().lower()
        resultados = []
        for comp in compradores:
            registro = {
                "codigo": comp.get("codigo") or comp.get("nCodigo") or comp.get("codigo_comprador"),
                "nome": comp.get("cDescricao") or comp.get("nome_comprador") or comp.get("descricao"),
            }
            if not termo:
                resultados.append(registro)
                continue
            texto = f"{registro['codigo']} {registro['nome'] or ''}".lower()
            if termo in texto:
                resultados.append(registro)
        return resultados


class ProductService:
    @staticmethod
    def list_products(search: str | None = None, page: int = 1, per_page: int = 50) -> dict:
        page = max(page, 1)
        per_page = max(min(per_page, 200), 1)
        body = {
            "pagina": page,
            "registros_por_pagina": per_page,
            "apenas_importado_api": "N",
            "filtrar_apenas_omiepdv": "N",
        }
        data = OmieClient.call(
            endpoint="/geral/produtos/",
            method="ListarProdutos",
            body=body,
        )
        produtos = (
            data.get("produto_servico_cadastro", [])
            or data.get("cadastros")
            or data.get("produtos")
            or []
        )
        termo = (search or "").strip().lower()
        resultados = []
        for prod in produtos:
            registro = {
                "codigo_produto": prod.get("codigo_produto") or prod.get("codigo") or prod.get("codigo_produto_integracao"),
                "descricao": prod.get("descricao") or prod.get("nome_produto"),
                "unidade": prod.get("unidade") or prod.get("unidade_medida"),
                "ncm": prod.get("ncm") or prod.get("codigo_ncm"),
                "valor_unitario": prod.get("valor_unitario") or prod.get("valor_unitario_produto"),
            }
            if not termo:
                resultados.append(registro)
                continue
            texto = " ".join([
                str(registro.get("codigo_produto") or ""),
                registro.get("descricao") or "",
                registro.get("ncm") or "",
            ]).lower()
            if termo in texto:
                resultados.append(registro)
        total = data.get("total_de_registros")
        total_paginas = data.get("total_de_paginas")
        pagina_atual = data.get("pagina", page)
        return {
            "results": resultados,
            "page": pagina_atual,
            "per_page": per_page,
            "total": total,
            "total_pages": total_paginas,
            "has_next": bool(total_paginas and pagina_atual < total_paginas),
            "has_previous": pagina_atual > 1,
        }
