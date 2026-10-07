"""Extração determinística de fatos D&O — provider offline, sem chamadas de rede.

Regras baseadas em alias de rótulos e localização de linha por página.
Usado como provider reprodutível (testes/demonstração) e como *fallback* do
extrator baseado em LLM.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from .models import PolicyDocument, PolicyFact
from .schema import FIELD_DEFINITIONS

ALIASES: dict[str, list[str]] = {
    "Seguradora": ["SEGURADORA"],
    "Vigência": ["VIGÊNCIA", "VIGENCIA"],
    "Âmbito geográfico": ["ÂMBITO GEOGRÁFICO", "AMBITO GEOGRAFICO"],
    "Limite máximo de responsabilidade": ["LIMITE MÁXIMO DE RESPONSABILIDADE", "LIMITE MAXIMO DE RESPONSABILIDADE"],
    "Limite agregado": ["LIMITE AGREGADO"],
    "Franquia / retenção": ["FRANQUIA / RETENÇÃO", "FRANQUIA", "RETENÇÃO"],
    "Cobertura A — indenização ao segurado": ["COBERTURA A", "INDENIZAÇÃO AO SEGURADO"],
    "Cobertura B — reembolso à sociedade": ["COBERTURA B", "REEMBOLSO À SOCIEDADE"],
    "Cobertura C — entidade": ["COBERTURA C", "COBERTURA PARA ENTIDADE"],
    "Custos de defesa": ["CUSTOS DE DEFESA"],
    "Custos de investigação": ["CUSTOS DE INVESTIGAÇÃO"],
    "Novas subsidiárias": ["NOVAS SUBSIDIÁRIAS"],
    "Período adicional de notificação": ["PERÍODO ADICIONAL DE NOTIFICAÇÃO", "PRAZO COMPLEMENTAR"],
    "Fraude ou dolo": ["FRAUDE OU DOLO", "FRAUDE", "DOLO"],
    "Danos corporais ou materiais": ["DANOS CORPORAIS OU MATERIAIS", "DANOS CORPORAIS"],
    "Poluição": ["POLUIÇÃO", "POLUICAO"],
    "Notificação de reclamações": ["NOTIFICAÇÃO DE RECLAMAÇÕES", "NOTIFICAÇÃO"],
    "Mudança de controle": ["MUDANÇA DE CONTROLE", "MUDANCA DE CONTROLE"],
    "Acordos e consentimento": ["ACORDOS E CONSENTIMENTO", "ACORDOS", "CONSENTIMENTO"],
}

EVIDENCIA_MAX = 500


def aliases_para(label: str) -> list[str]:
    """Retorna os termos de busca (maiúsculos/acentuados) para um rótulo do schema."""
    return ALIASES.get(label, [label.upper()])


def localizar_linha(text_by_page: dict[int, str], aliases: list[str]) -> tuple[int, str] | None:
    """Localiza a primeira linha correspondente aos aliases, com número da página.

    Args:
        text_by_page: Texto por número de página.
        aliases: Termos de busca normalizados em maiúsculas.

    Returns:
        Tupla ``(página, linha)`` ou ``None`` quando nenhum alias aparece.
    """
    for page, text in text_by_page.items():
        lines = [line.strip() for line in text.splitlines()]
        for index, line in enumerate(lines):
            normalized = line.upper()
            if not any(alias in normalized for alias in aliases):
                continue
            if ":" in line:
                return page, line
            if index + 1 < len(lines) and lines[index + 1]:
                return page, f"{line}: {lines[index + 1]}"
            return page, line
    return None


def normalizar_valor(value: Any) -> str | None:
    """Normaliza um valor para comparação (minúsculas, espaços colapsados, ``R$`` → ``brl``)."""
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip().lower()
    return text.replace("r$", "brl ")


def remover_acentos(value: str) -> str:
    """Remove acentuação preservando os caracteres base (comparações de rótulo)."""
    return "".join(char for char in unicodedata.normalize("NFKD", value) if not unicodedata.combining(char))


class RuleBasedExtractor:
    """Extrator offline determinístico para testes e documentos didáticos controlados."""

    name = "rule-based-offline"
    model = "deterministic-extractor-v1"

    def extract(self, document: PolicyDocument) -> list[PolicyFact]:
        """Extrai todos os campos do schema a partir do texto das páginas.

        Args:
            document: Documento já ingestado com páginas e texto.

        Returns:
            Um :class:`PolicyFact` por campo do schema (presente ou ``not_found``).
        """
        text_by_page = {page.page_number: page.text for page in document.pages}
        return [self._extract_field(document, field, text_by_page) for field in FIELD_DEFINITIONS]

    @staticmethod
    def _extract_field(document: PolicyDocument, field: dict[str, str], text_by_page: dict[int, str]) -> PolicyFact:
        label = field["label"]
        match = localizar_linha(text_by_page, aliases_para(label))
        if not match:
            return PolicyFact(
                document_id=document.document_id,
                category=field["category"],
                label=label,
                value=None,
                status="not_found",
                confidence=0.35,
                page=None,
                evidence="Informação não localizada no texto extraído.",
                normalized_value=None,
                source=document.source,
            )
        page, line = match
        value = line.split(":", 1)[1].strip() if ":" in line else line.strip()
        return PolicyFact(
            document_id=document.document_id,
            category=field["category"],
            label=label,
            value=value,
            status="present",
            confidence=0.98,
            page=page,
            evidence=line[:EVIDENCIA_MAX],
            normalized_value=normalizar_valor(value),
            source=document.source,
        )
