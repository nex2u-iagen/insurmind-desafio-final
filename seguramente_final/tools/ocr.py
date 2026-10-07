"""Ferramenta OCR — Tesseract para imagens e PDF digitalizado.

Fornece :class:`OcrEngine` (usado pela camada de ingestão por injeção de
dependência) e a ferramenta registrada :func:`extrair_texto_ocr` para os
agentes. Falhas nunca propagam (seguem com texto vazio), mas sempre geram
registro de log com a causa raiz para diagnóstico.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .registry import registrar_ferramenta

logger = logging.getLogger(__name__)

IDIOMAS_OCR = "por+eng"
LIMITE_MINIMO_TEXTO = 20


class OcrEngine:
    """Extrai texto de imagens via Tesseract, com log de diagnóstico em falhas."""

    def __init__(self, idiomas: str = IDIOMAS_OCR) -> None:
        self.idiomas = idiomas

    def reconhecer(self, image: object) -> str:
        """Retorna o texto reconhecido ou string vazia em falha (logado).

        Args:
            image: Objeto compatível com Pillow/``pytesseract``.

        Returns:
            Texto extraído sem espaços nas pontas ou ``""`` se o OCR falhar.
        """
        try:
            import pytesseract

            texto = str(pytesseract.image_to_string(image, lang=self.idiomas)).strip()
            if not texto:
                logger.warning("OCR devolveu texto vazio (idiomas=%s).", self.idiomas)
            return texto
        except Exception as exc:  # noqa: BLE001 — OCR é melhor esforço; ingestão segue com texto vazio
            logger.warning("OCR indisponível (%s: %s). Instale tesseract e tessdata por/eng.", type(exc).__name__, exc)
            return ""

    def reconhecer_arquivo(self, path: object) -> str:
        """Abre a imagem em ``path`` e delega ao OCR.

        Args:
            path: Caminho da imagem (PNG/JPEG/TIFF).

        Returns:
            Texto reconhecido ou ``""`` em falha de abertura/OCR.
        """
        try:
            from PIL import Image

            with Image.open(path) as image:
                return self.reconhecer(image)
        except Exception as exc:  # noqa: BLE001 — melhor esforço com diagnóstico
            logger.warning("Falha ao abrir imagem para OCR: %s: %s", type(exc).__name__, exc)
            return ""

    def reconhecer_pagina_pdf(self, path: object, page_number: int) -> str:
        """Renderiza a página de um PDF digitalizado e aplica OCR.

        Args:
            path: Caminho do PDF.
            page_number: Número da página (base 1).

        Returns:
            Texto reconhecido ou ``""`` quando a renderização/OCR falha.
        """
        try:
            from pdf2image import convert_from_path

            images = convert_from_path(str(path), dpi=180, first_page=page_number, last_page=page_number)
            if not images:
                logger.warning("pdf2image não retornou imagem da página %s de %s.", page_number, path)
                return ""
            return self.reconhecer(images[0])
        except Exception as exc:  # noqa: BLE001 — melhor esforço com diagnóstico
            logger.warning(
                "Falha ao renderizar página %s do PDF para OCR: %s: %s", page_number, type(exc).__name__, exc
            )
            return ""


@registrar_ferramenta("extrair_texto_ocr", "Reconhece texto em imagem ou página de PDF digitalizado (Tesseract).")
def extrair_texto_ocr(caminho: str | Path) -> str:
    """Extrai o texto de um arquivo por OCR, em melhor esforço.

    Args:
        caminho: Imagem (PNG/JPEG/TIFF) ou PDF digitalizado (página 1).

    Returns:
        Texto reconhecido ou ``""`` quando o arquivo/OCR falha (logado).
    """
    path = Path(caminho)
    motor = OcrEngine()
    if path.suffix.lower() == ".pdf":
        return motor.reconhecer_pagina_pdf(path, 1)
    return motor.reconhecer_arquivo(path)
