import logging
import base64
from typing import Optional
from django.db import models
from omie_api.client import OmieAPIClient, OmieAPIException
from .models import PurchaseOrderClosureLog
from django.db import transaction
from attachments.models import AttachmentSyncLog
from .models import PurchaseOrderIntegration, PurchaseOrderFinanceMap

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

class FullFlowPurchaseOrderService:
    """
    Fluxo:
    - criar pedido de compra na Omie
    - anexar arquivos
    - quando finalizado, criar conta a pagar + copiar anexos
    """

    def __init__(self, omie_client: OmieAPIClient | None = None):
        self.omie = omie_client or OmieAPIClient.from_settings()

    @transaction.atomic
    def criar_pedido_com_anexos(self, pedido_data: dict, arquivos) -> PurchaseOrderIntegration:
        resp = self.omie.incluir_pedido_compra(pedido_data)
        ncodped = resp.get("nCodPed")

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
        """
        Ajuste a regra aqui conforme o status retornado pelo Omie.
        Exemplo: considerar finalizado quando cStatus == 'Fechado' ou 'Encerrado'.
        """
        status = (dados_pedido or {}).get("cStatus", "").lower()
        return status in ("fechado", "encerrado")

    def _montar_conta_pagar(self, dados_pedido: dict, cod_int_pedido: str | None) -> dict:
        """
        Monte aqui o payload de IncluirContaPagar conforme regra do cliente.
        O importante: usar codigo_lancamento_integracao pra idempotência.
        """
        total = dados_pedido.get("nValorTotal", 0)
        fornecedor = dados_pedido.get("codigo_cliente_fornecedor")

        return {
            "codigo_lancamento_integracao": f"PO-{cod_int_pedido or dados_pedido.get('nCodPed')}",
            "codigo_cliente_fornecedor": fornecedor,
            "valor_documento": total,
            "data_vencimento": dados_pedido.get("dDataPrevisao", dados_pedido.get("dDataEmissao")),
            "numero_documento": str(dados_pedido.get("nCodPed")),
            # incluir demais campos obrigatórios do Omie aqui
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
        - mapa de pedidos
        - criação de contas a pagar quando aplicável
        - cópia de anexos
        """

        def __init__(self, omie_client: OmieAPIClient | None = None):
            self.omie = omie_client or OmieAPIClient.from_settings()
            self.full_flow = FullFlowPurchaseOrderService(self.omie)

        def processar(self):
            """
            Exemplo simples: você pode especializar a busca de pedidos/recebimentos
            conforme necessidade do cliente (datas, status, etc.).
            """
            # Aqui você pode usar ListarRecebimentos ou outro serviço para encontrar
            # movimentos que ainda não estão mapeados.
            # Abaixo está um esqueleto genérico:

            # 1) buscar recebimentos
            resp = self.omie.listar_recebimentos({"nPagina": 1, "nRegistrosPorPagina": 50})
            recebimentos = resp.get("recebimentos", [])

            for rec in recebimentos:
                n_cod_ped = rec.get("nCodPedido")
                n_id_receb = rec.get("nIdReceb")

                if not n_cod_ped:
                    continue

                po, _ = PurchaseOrderIntegration.objects.get_or_create(
                    ncodped_omie=n_cod_ped,
                    defaults={
                        "origem": "omie",
                        "metodo_criacao": "robo",
                    },
                )

                # se ainda não tem financeiro, cria
                if not hasattr(po, "finance_map"):
                    # monte payload de conta a pagar baseado no rec
                    conta_payload = {
                        "codigo_lancamento_integracao": f"ROBO-PO-{n_cod_ped}",
                        "codigo_cliente_fornecedor": rec.get("nIdFornecedor") or rec.get("codigo_cliente_fornecedor"),
                        "valor_documento": rec.get("nValorNFe"),
                        "data_vencimento": rec.get("dVencimento") or rec.get("dEmissaoNFe"),
                        "numero_documento": str(n_cod_ped),
                    }
                    resp_cp = self.omie.incluir_conta_pagar(conta_payload)
                    cod_lanc = resp_cp.get("codigo_lancamento_omie")

                    fmap = PurchaseOrderFinanceMap.objects.create(
                        purchase_order=po,
                        codigo_lancamento_omie=cod_lanc,
                        metodo_criacao="robo",
                        anexos_sincronizados=False,
                    )

                    # copia anexos da nota (com-recebimento) para conta-pagar
                    self._copiar_anexos_recebimento_para_financeiro(
                        n_id_receb,
                        fmap,
                    )

        def _copiar_anexos_recebimento_para_financeiro(self, n_id_receb: int, fmap: PurchaseOrderFinanceMap):
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
                    logger.exception("Falha ao copiar anexo do recebimento %s", n_id_receb)
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