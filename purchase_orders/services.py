import base64
import logging
import requests
from django.conf import settings

from django.db import transaction

from omie_api.client import OmieAPIClient, OmieAPIException
from attachments.models import AttachmentSyncLog
from .models import (
    PurchaseOrderClosureLog,
    PurchaseOrderIntegration,
    PurchaseOrderFinanceMap,
)

logger = logging.getLogger(__name__)

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
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()


class SupplierService:
    """
    Consulta fornecedores no Omie usando ListarClientes,
    filtrando apenas quem é fornecedor.
    """

    @classmethod
    def list_suppliers(cls, search: str | None = None, page: int = 1, per_page: int = 50):
        body = {
            "pagina": page,
            "registros_por_pagina": per_page,
            "apenas_importado_api": "N",
        }

        # filtro básico por nome/razão/CPFCNPJ
        if search:
            body["pesquisa"] = {
                "campo": "RAZAO_SOCIAL",
                "valor": search,
            }

        data = OmieClient.call(
            endpoint="/geral/clientes/",
            method="ListarClientes",
            body=body,
        )

        results = []
        for item in data.get("clientes_cadastro", []):
            # ajuste essa condição conforme o que o Omie retornar no seu ambiente
            tipo = (item.get("cTipo") or "").upper()
            if tipo in ("F", "FORN", "FORNECEDOR", ""):
                results.append(
                    {
                        "id": item.get("codigo_cliente_omie"),
                        "nome": item.get("razao_social") or item.get("nome_fantasia"),
                        "cnpj_cpf": item.get("cnpj_cpf"),
                    }
                )

        return results


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
        resp = self.omie.incluir_pedido_compra(pedido_data)
        ncodped = resp.get("nCodPed")
        if not ncodped:
            raise OmieAPIException(f"Resposta Omie sem nCodPed: {resp}")

        po = PurchaseOrderIntegration.objects.create(
            cod_int_pedido=pedido_data.get("cCodIntPed"),
            ncodped_omie=ncodped,
            origem="backoffice",
            metodo_criacao="sistema",
        )

        for arquivo in arquivos:
            conteudo = arquivo.read()
            b64 = base64.b64encode(conteudo).decode()
            self.omie.incluir_anexo(
                c_tabela="pedido-compra",
                n_id=ncodped,
                nome_arquivo=arquivo.name,
                arquivo_base64=b64,
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
