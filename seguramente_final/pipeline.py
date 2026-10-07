"""Orquestração do MVP D&O — etapas do edital em um único fluxo."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from .compare import compare_documents, resumir_diferencas
from .ingest import load_document
from .models import AnalysisResult, ComparisonRow, PolicyDocument, PolicyFact
from .motor_llm import LLMError, criar_cliente
from .rules import RuleBasedExtractor
from .storage import PolicyStore
from .tools.extrator import ExtratorLLM
from .tools.resumidor import ResumidorLLM

logger = logging.getLogger(__name__)

PROVIDERS_OFFLINE = {"offline"}
PROVIDERS_LLM = {"openai", "groq", "google"}


class ExtratorFatos(Protocol):
    """Contrato do extrator de fatos (offline ou LLM), injetável no pipeline."""

    name: str
    model: str

    def extract(self, document: PolicyDocument) -> list[PolicyFact]:
        """Retorna um fato por campo do schema para o documento."""
        ...


def analyze_policies(
    paths: Iterable[str | Path],
    names: Iterable[str] | None = None,
    source: str = "documento fornecido para demonstração",
    provider_mode: str = "offline",
    store_path: str | Path = "data/policies.db",
    extractor: ExtratorFatos | None = None,
) -> AnalysisResult:
    """Executa as sete etapas preferenciais do edital: ingerir, extrair, comparar, persistir e resumir.

    Args:
        paths: Dois caminhos de apólices (PDF ou imagem).
        names: Nomes de exibição alinhados a ``paths``.
        source: Proveniência registrada nos documentos.
        provider_mode: ``offline`` (determinístico) ou ``openai`` (LLM).
        store_path: Caminho do SQLite local.
        extractor: Extrator injetável; substitui a fábrica quando informado.

    Returns:
        :class:`AnalysisResult` com documentos, comparação, resumo e provider.

    Raises:
        ValueError: Menos de duas apólices ou ``provider_mode`` inválido.
        LLMError: Falha de chamada no modo ``openai``.
    """
    path_list = list(paths)
    if len(path_list) < 2:
        raise ValueError("A comparação exige pelo menos duas apólices.")
    name_list = list(names or [])
    documents = [
        load_document(path, name=name_list[index] if index < len(name_list) else Path(path).name, source=source)
        for index, path in enumerate(path_list)
    ]
    extrator = extractor or _criar_extrator(provider_mode)
    for document in documents:
        document.facts = extrator.extract(document)
    rows = compare_documents(documents[0], documents[1])
    fallback = bool(getattr(extrator, "fallback_aplicado", False))
    try:
        summary = _resumir(provider_mode, extrator, rows)
    except LLMError as exc:
        logger.warning("Resumo por LLM falhou (%s); usando resumo offline.", exc)
        summary = resumir_diferencas(rows)
        fallback = True
    _persistir(store_path, documents, rows)
    if fallback:
        logger.warning(
            "Extração LLM caiu para o modo offline (provider declarado=%s); o resultado sai com fallback_offline=true.",
            extrator.name,
        )
    logger.info(
        "Análise concluída: provider=%s model=%s campos=%s fallback_offline=%s",
        extrator.name,
        extrator.model,
        len(rows),
        fallback,
    )
    return AnalysisResult(documents, rows, summary, extrator.name, extrator.model, fallback)


def _criar_extrator(provider_mode: str) -> ExtratorFatos:
    """Fábrica dos providers — único ponto que instancia extrações concretas."""
    if provider_mode in PROVIDERS_LLM:
        return ExtratorLLM(cliente=criar_cliente(provider_mode))
    if provider_mode in PROVIDERS_OFFLINE:
        return RuleBasedExtractor()
    raise ValueError("provider_mode deve ser 'offline', 'openai', 'groq' ou 'google'.")


def _resumir(provider_mode: str, extractor: ExtratorFatos, rows: list[ComparisonRow]) -> str:
    """Gera o resumo executivo conforme o provider (LLM ou regras offline)."""
    if provider_mode in PROVIDERS_LLM:
        cliente = getattr(extractor, "cliente", None)
        if cliente is None:
            raise LLMError("Resumo LLM exige extrator com cliente; injete um ExtratorLLM.")
        return ResumidorLLM(cliente).summarize(rows)
    return resumir_diferencas(rows)


def _persistir(store_path: str | Path, documents: list[PolicyDocument], rows: list[ComparisonRow]) -> None:
    """Grava documentos, páginas, fatos e comparações no SQLite local."""
    store = PolicyStore(store_path)
    for document in documents:
        store.save_document(document)
    store.save_comparison(documents[0], documents[1], rows)
