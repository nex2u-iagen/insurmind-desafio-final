"""Recepção, validação e extração de páginas de documentos PDF/imagem."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from .models import DocumentPage, PolicyDocument
from .telemetria import evento_ferramenta

if TYPE_CHECKING:  # import em tempo de checagem: tools.ocr importa tools → tools.documento → ingest (ciclo real)
    from .tools.ocr import OcrEngine

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}


class IngestionError(RuntimeError):
    """Erro controlado na leitura de documentos."""


def document_id_for(path: str | Path) -> str:
    """Calcula o identificador curto e estável do documento (SHA-256 truncado)."""
    data = Path(path).read_bytes()
    return hashlib.sha256(data).hexdigest()[:12].upper()


def extract_pdf_pages(path: str | Path, ocr: OcrEngine | None = None, forcar_ocr: bool = False) -> list[DocumentPage]:
    """Extrai o texto de cada página de um PDF, acionando OCR para páginas sem camada textual.

    Args:
        path: Caminho do PDF.
        ocr: Motor OCR injetável; usa :class:`OcrEngine` padrão quando ausente.
        forcar_ocr: Simulação — aciona o OCR também em páginas com texto nativo
            (publica ``tool:extrair_texto_ocr`` no painel); o texto nativo é
            preservado para manter a análise inalterada.

    Returns:
        Uma :class:`DocumentPage` por página, com método de extração registrado.

    Raises:
        IngestionError: Quando o ``pypdf`` não está instalado.
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise IngestionError("Instale pypdf para ler PDFs.") from exc
    from .tools.ocr import LIMITE_MINIMO_TEXTO, OcrEngine

    motor = ocr or OcrEngine()
    document_id = document_id_for(path)
    reader = PdfReader(str(path))
    pages: list[DocumentPage] = []
    for index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        method = "pdf-text"
        sem_texto = len(text) < LIMITE_MINIMO_TEXTO
        if sem_texto or forcar_ocr:
            if sem_texto:
                logger.info("Página %s de %s sem texto nativo; acionando OCR.", index, path)
            else:
                logger.info("Página %s de %s: OCR forçado (simulação); texto nativo será preservado.", index, path)
            with evento_ferramenta("extrair_texto_ocr"):
                texto_ocr = motor.reconhecer_pagina_pdf(path, index) or ""
            if sem_texto:
                text = texto_ocr or text
                method = "ocr" if len(text) >= LIMITE_MINIMO_TEXTO else "pdf-text-empty"
                if method == "pdf-text-empty":
                    logger.warning("OCR não recuperou texto da página %s de %s.", index, path)
        pages.append(DocumentPage(document_id, index, text, method))
    return pages


def extract_image_pages(path: str | Path, ocr: OcrEngine | None = None) -> list[DocumentPage]:
    """Reconhece o texto de uma imagem (foto ou página digitalizada) como documento de página única.

    Sem motor injetado, o reconhecimento passa pela ferramenta registrada
    ``extrair_texto_ocr`` (publica ``tool:extrair_texto_ocr``); com motor
    injetado (injeção de dependência), o evento é publicado explicitamente.

    Args:
        path: Caminho da imagem suportada.
        ocr: Motor OCR injetável; usa a ferramenta registrada quando ausente.

    Returns:
        Lista com uma única página cujo método indica sucesso (``ocr``) ou falha.
    """
    from .tools.ocr import extrair_texto_ocr

    if ocr is None:
        text = extrair_texto_ocr(path)
    else:
        with evento_ferramenta("extrair_texto_ocr"):
            text = ocr.reconhecer_arquivo(path)
    document_id = document_id_for(path)
    method = "ocr" if text else "ocr-empty"
    if not text:
        logger.warning("OCR não recuperou texto da imagem %s.", path)
    return [DocumentPage(document_id, 1, text, method)]


def load_document(
    path: str | Path,
    name: str | None = None,
    source: str = "documento fornecido pelo usuário",
    ocr: OcrEngine | None = None,
    forcar_ocr: bool = False,
) -> PolicyDocument:
    """Valida o arquivo e o carrega como :class:`PolicyDocument` com páginas extraídas.

    Args:
        path: Caminho do PDF ou imagem.
        name: Nome de exibição; usa o nome do arquivo quando ausente.
        source: Proveniência do documento para rastreabilidade.
        ocr: Motor OCR injetável nas extrações dependentes de reconhecimento.
        forcar_ocr: Simulação — aciona o OCR também em PDFs com texto nativo.

    Returns:
        Documento com identificador, páginas e método de extração por página.

    Raises:
        IngestionError: Formato não suportado, arquivo ausente ou vazio.
    """
    path_obj = Path(path)
    if path_obj.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise IngestionError(f"Formato não suportado: {path_obj.suffix or 'sem extensão'}")
    if not path_obj.exists() or path_obj.stat().st_size == 0:
        raise IngestionError(f"Arquivo inexistente ou vazio: {path_obj}")
    if path_obj.suffix.lower() == ".pdf":
        pages = extract_pdf_pages(path_obj, ocr=ocr, forcar_ocr=forcar_ocr)
    else:
        pages = extract_image_pages(path_obj, ocr=ocr)
    return PolicyDocument(
        document_id=document_id_for(path_obj),
        name=name or path_obj.name,
        path=str(path_obj),
        source=source,
        pages=pages,
    )


def exigir_documentos_distintos(document_ids: list[str]) -> None:
    """Impede comparar um documento consigo mesmo (upload/CLI duplicado).

    O ``document_id`` é o SHA-256 do conteúdo: dois caminhos diferentes com o
    mesmo arquivo geram o mesmo id e a comparação sairia "sem diferenças",
    passando despercebida ao usuário.

    Args:
        document_ids: Identificadores dos documentos da análise, em ordem.

    Raises:
        ValueError: Dois ids idênticos (o mesmo arquivo em mais de uma posição).
    """
    vistos: set[str] = set()
    for identificador in document_ids:
        if identificador in vistos:
            raise ValueError(
                f"As apólices informadas são o mesmo arquivo (id {identificador}). "
                "Envie dois documentos distintos para comparar."
            )
        vistos.add(identificador)
