"""Ferramentas dos sub-agentes — registry com allowlist imposta em código."""

from __future__ import annotations

from .documento import comparar_apolices, ingestar_documentos, resumir_comparacao
from .extrator import ExtratorLLM
from .ocr import OcrEngine, extrair_texto_ocr
from .registry import (
    ALLOWLIST,
    AgenteFerramentas,
    Ferramenta,
    executar_ferramenta,
    listar_ferramentas,
    obter_ferramenta,
    registrar_ferramenta,
)
from .resumidor import ResumidorLLM

__all__ = [
    "ALLOWLIST",
    "AgenteFerramentas",
    "ExtratorLLM",
    "Ferramenta",
    "OcrEngine",
    "ResumidorLLM",
    "comparar_apolices",
    "executar_ferramenta",
    "extrair_texto_ocr",
    "ingestar_documentos",
    "listar_ferramentas",
    "obter_ferramenta",
    "registrar_ferramenta",
    "resumir_comparacao",
]
