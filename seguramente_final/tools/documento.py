"""Ferramentas de documento: ingerir, comparar e resumir apólices."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..compare import compare_documents, resumir_diferencas
from ..ingest import load_document
from ..models import ComparisonRow, PolicyDocument
from ..rules import RuleBasedExtractor
from .registry import registrar_ferramenta
from .resumidor import ResumidorLLM


def _como_documento(alvo: str | Path | dict[str, Any] | PolicyDocument, extrator: Any = None) -> PolicyDocument:
    """Aceita caminho, dict serializado ou instância de :class:`PolicyDocument`."""
    if isinstance(alvo, PolicyDocument):
        doc = alvo
    elif isinstance(alvo, dict):
        doc = PolicyDocument.from_dict(alvo)
    else:
        doc = load_document(alvo)
    if not doc.facts:
        doc.facts = (extrator or RuleBasedExtractor()).extract(doc)
    return doc


def _como_linha(alvo: dict[str, Any] | ComparisonRow) -> ComparisonRow:
    """Aceita dict serializado ou instância de :class:`ComparisonRow`."""
    return alvo if isinstance(alvo, ComparisonRow) else ComparisonRow(**alvo)


@registrar_ferramenta("ingestar_documentos", "Ingesta apólices em dicionários JSON-safe.")
def ingestar_documentos(
    caminhos: list[str | Path],
    nomes: list[str] | None = None,
    forcar_ocr: bool = False,
) -> list[dict[str, Any]]:
    """Ingesta de apólices (PDF/imagem) em listas de dicionários JSON-safe.

    Args:
        caminhos: Caminhos dos documentos.
        nomes: Nomes de exibição alinhados aos caminhos.
        forcar_ocr: Simulação — aciona o OCR também em PDFs com texto nativo.

    Returns:
        Documentos serializados em dicts JSON-safe.
    """
    lista_caminhos = [str(c) for c in caminhos]
    nomes = list(nomes or [])
    documentos = []
    for indice, caminho in enumerate(lista_caminhos):
        nome = nomes[indice] if indice < len(nomes) else Path(caminho).name
        documentos.append(load_document(caminho, name=nome, forcar_ocr=forcar_ocr).to_dict())
    return documentos


@registrar_ferramenta("comparar_apolices", "Compara duas apólices e retorna linhas com evidência.")
def comparar_apolices(
    alvo_a: str | Path | dict[str, Any] | PolicyDocument,
    alvo_b: str | Path | dict[str, Any] | PolicyDocument,
    extrator: Any = None,
) -> list[dict[str, Any]]:
    """Compara duas apólices (caminho, dict ou modelo) em 19 linhas JSON-safe."""
    linhas = compare_documents(_como_documento(alvo_a, extrator), _como_documento(alvo_b, extrator))
    return [linha.to_dict() for linha in linhas]


@registrar_ferramenta("resumir_comparacao", "Resume as diferenças encontradas na comparação.")
def resumir_comparacao(
    linhas: list[dict[str, Any] | ComparisonRow],
    cliente: Any = None,
    memoria_contexto: list[str] | None = None,
    achados: list[dict[str, Any]] | None = None,
    pedido_usuario: str = "",
) -> str:
    """Resume as diferenças: offline por regras ou via cliente LLM injetado.

    Args:
        linhas: Linhas comparadas (dict ou modelo).
        cliente: Cliente LLM opcional (``None`` → resumo offline determinístico).
        memoria_contexto: Lembranças de análises anteriores injetadas no prompt.
        achados: Vereditos dos especialistas com trechos e páginas recuperados.
        pedido_usuario: Solicitação original para orientar a síntese.

    Returns:
        Texto do resumo.
    """
    rows = [_como_linha(linha) for linha in linhas]
    if cliente is None:
        return resumir_diferencas(rows)
    return ResumidorLLM(cliente).summarize(
        rows,
        memoria_contexto=memoria_contexto,
        achados=achados,
        pedido_usuario=pedido_usuario,
    )
