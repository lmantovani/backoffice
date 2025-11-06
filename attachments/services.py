import logging
import time
from typing import List, Tuple, Optional
from django.db import models
from omie_api.client import OmieAPIClient, OmieAPIException
from .models import AttachmentTransferLog, AttachmentIntegrationMap

logger = logging.getLogger(__name__)

class AttachmentTransferService:
    def __init__(self):
        self.client = OmieAPIClient()

    def _extrair_tamanho(self, anexo: dict) -> int:
        # Tenta diferentes chaves comuns para tamanho
        for key in ('nTamanho', 'tamanho', 'nBytes', 'bytes'):
            v = anexo.get(key)
            if isinstance(v, int):
                return v
            try:
                return int(v) if v is not None else 0
            except (TypeError, ValueError):
                continue
        return 0

    def transferir_anexos(self, origem_id: int, destino_id: int, origem_tabela: str = 'com-recebimento', destino_tabela: str = 'conta_a_pagar') -> AttachmentTransferLog:
        inicio = time.monotonic()
        log = AttachmentTransferLog.objects.create(
            origem_tabela=origem_tabela,
            origem_id=origem_id,
            destino_tabela=destino_tabela,
            destino_id=destino_id,
            status='pending'
        )
        try:
            log.mark_as_processing()
            logger.info(
                "[RF-001] Iniciando transferência de anexos",
                extra={"origem_id": origem_id, "destino_id": destino_id, "origem_tabela": origem_tabela, "destino_tabela": destino_tabela, "log_id": log.id}
            )

            # Lista anexos já existentes no destino para evitar duplicatas
            anexos_destino = self.client.listar_anexos(destino_tabela, destino_id) or []
            nomes_existentes = {a.get('cNomeArquivo') for a in anexos_destino if a.get('cNomeArquivo')}
            pares_existentes: set[Tuple[str, int]] = set()
            for a in anexos_destino:
                nome = a.get('cNomeArquivo')
                tam = self._extrair_tamanho(a)
                if nome:
                    pares_existentes.add((nome, tam))

            # Lista anexos da origem
            anexos_origem = self.client.listar_anexos(origem_tabela, origem_id) or []
            log.total_anexos = len(anexos_origem)

            transferidos: List[dict] = []
            duplicados = 0
            sem_conteudo = 0
            erros_inclusao = 0

            for anexo in anexos_origem:
                nome = anexo.get('cNomeArquivo')
                n_id_anexo = anexo.get('nIdAnexo')
                tam = self._extrair_tamanho(anexo)
                if not nome:
                    continue
                # Idempotência por nome e (se disponível) tamanho
                if nome in nomes_existentes or (nome, tam) in pares_existentes:
                    duplicados += 1
                    continue
                conteudo = self.client.obter_anexo(n_id_anexo)
                base64_file = conteudo.get('cArquivo')
                if not base64_file:
                    sem_conteudo += 1
                    continue
                try:
                    self.client.incluir_anexo(
                        tabela='conta_a_pagar', n_id=destino_id,
                        nome_arquivo=nome, arquivo_base64=base64_file
                    )
                    transferidos.append({'nome': nome, 'nIdAnexoOrigem': n_id_anexo, 'tamanho': tam})
                    # Atualiza conjuntos para evitar incluir novamente no mesmo run
                    nomes_existentes.add(nome)
                    pares_existentes.add((nome, tam))
                except OmieAPIException as e:
                    erros_inclusao += 1
                    # Loga faultstring se presente
                    msg = str(e)
                    logger.error(
                        f"[RF-001] Erro ao incluir anexo '{nome}' no destino {destino_id}: {msg}",
                        extra={"origem_id": origem_id, "destino_id": destino_id, "log_id": log.id}
                    )

            elapsed_ms = int((time.monotonic() - inicio) * 1000)
            # Preenche detalhes e marca sucesso
            detalhes = {
                'contagem_origem': len(anexos_origem),
                'contagem_destino_inicial': len(anexos_destino),
                'duplicados': duplicados,
                'sem_conteudo': sem_conteudo,
                'erros_inclusao': erros_inclusao,
                'elapsed_ms': elapsed_ms,
            }
            log.detalhes = detalhes
            log.save(update_fields=['total_anexos', 'detalhes', 'updated_at'])

            logger.info(
                f"[RF-001] Transferência concluída: {len(transferidos)} incluídos, {duplicados} duplicados, {elapsed_ms}ms",
                extra={"origem_id": origem_id, "destino_id": destino_id, "log_id": log.id}
            )
            log.mark_as_success(transferidos)
            return log
        except OmieAPIException as e:
            elapsed_ms = int((time.monotonic() - inicio) * 1000)
            msg = str(e)
            logger.error(
                f"[RF-001] Erro Omie ao transferir anexos {origem_id}->{destino_id}: {msg} ({elapsed_ms}ms)",
                extra={"origem_id": origem_id, "destino_id": destino_id, "log_id": log.id}
            )
            log.mark_as_failed(msg)
            return log
        except Exception as e:
            elapsed_ms = int((time.monotonic() - inicio) * 1000)
            logger.exception(
                f"[RF-001] Erro inesperado na transferência de anexos ({elapsed_ms}ms)",
                extra={"origem_id": origem_id, "destino_id": destino_id, "log_id": log.id}
            )
            log.mark_as_failed(f"Erro inesperado: {e}")
            return log

    def processar_transferencias_pendentes(self):
        pendentes = AttachmentTransferLog.objects.filter(
            status__in=['pending', 'failed'], tentativas__lt=models.F('max_tentativas')
        )
        resultados = []
        for p in pendentes:
            # Checa pode_retentar para cada item para respeitar regra de negócio
            if not p.pode_retentar:
                continue
            resultados.append(self.transferir_anexos(p.origem_id, p.destino_id))
        return resultados

    def registrar_mapeamento_para_transferencia(
        self,
        origem_recebimento_id: int,
        destino_conta_pagar_id: int,
        numero_nf: Optional[str] = None,
        iniciar_transferencia: bool = False,
        assincrono: bool = True,
    ) -> AttachmentTransferLog:
        """
        Registra o mapeamento origem(nIdReceb)->destino(nCodTitulo) e prepara a transferência (RF-001).
        - Cria/garante o AttachmentIntegrationMap.
        - Cria um AttachmentTransferLog pendente (se ainda não existir um bem-sucedido para o par).
        - Opcionalmente dispara a transferência (síncrona ou via Celery).
        """
        # Garante o mapa de integração
        AttachmentIntegrationMap.objects.get_or_create(
            origem_recebimento_id=origem_recebimento_id,
            destino_conta_pagar_id=destino_conta_pagar_id,
            defaults={'numero_nf': numero_nf} if numero_nf else {}
        )

        # Evita duplicar se já há sucesso para este par
        existente_sucesso = AttachmentTransferLog.objects.filter(
            origem_id=origem_recebimento_id,
            destino_id=destino_conta_pagar_id,
            status='success'
        ).first()
        if existente_sucesso:
            return existente_sucesso

        # Reusa pendente/failed existente ou cria novo
        log = AttachmentTransferLog.objects.filter(
            origem_id=origem_recebimento_id,
            destino_id=destino_conta_pagar_id,
            status__in=['pending', 'failed']
        ).first()
        if not log:
            log = AttachmentTransferLog.objects.create(
                origem_id=origem_recebimento_id,
                destino_id=destino_conta_pagar_id,
                status='pending'
            )

        if iniciar_transferencia:
            if assincrono:
                # Import tardio para evitar import circular
                try:
                    from .tasks import transferir_anexos_task
                    transferir_anexos_task.delay(origem_recebimento_id, destino_conta_pagar_id)
                except Exception:
                    logger.exception("Falha ao enfileirar task de transferência de anexos")
            else:
                self.transferir_anexos(origem_recebimento_id, destino_conta_pagar_id)

        return log