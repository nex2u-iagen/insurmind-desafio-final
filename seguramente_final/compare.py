"""Comparação explicável de fatos extraídos de duas apólices."""

from __future__ import annotations

from .ingest import exigir_documentos_distintos
from .models import ComparisonRow, PolicyDocument, PolicyFact
from .schema import FIELD_DEFINITIONS


def compare_documents(document_a: PolicyDocument, document_b: PolicyDocument) -> list[ComparisonRow]:
    """Compara os fatos das duas apólices campo a campo, alinhando pelo schema.

    Args:
        document_a: Apólice A com fatos extraídos.
        document_b: Apólice B com fatos extraídos.

    Returns:
        Uma :class:`ComparisonRow` por campo do schema, com status e evidências.

    Raises:
        ValueError: As duas apólices são o mesmo arquivo (id idêntico).
    """
    exigir_documentos_distintos([document_a.document_id, document_b.document_id])
    facts_a = {(fact.category, fact.label): fact for fact in document_a.facts}
    facts_b = {(fact.category, fact.label): fact for fact in document_b.facts}
    rows: list[ComparisonRow] = []
    for field in FIELD_DEFINITIONS:
        key = (field["category"], field["label"])
        fact_a = facts_a.get(key) or _not_found(document_a.document_id, key)
        fact_b = facts_b.get(key) or _not_found(document_b.document_id, key)
        status, difference = _compare_values(fact_a, fact_b)
        rows.append(
            ComparisonRow(
                category=key[0],
                label=key[1],
                policy_a=fact_a.value,
                policy_b=fact_b.value,
                difference=difference,
                status=status,
                evidence_a=fact_a.evidence,
                evidence_b=fact_b.evidence,
                page_a=fact_a.page,
                page_b=fact_b.page,
            )
        )
    return rows


def resumir_diferencas(rows: list[ComparisonRow]) -> str:
    """Resume as diferenças por contagem em categoria, sem chamadas de rede.

    Args:
        rows: Linhas da tabela comparativa.

    Returns:
        Resumo executivo com contagem e alerta de que não é parecer jurídico.
    """
    differences = [row for row in rows if row.status not in {"igual", "ambos_ausentes"}]
    if not differences:
        return "Não foram identificadas diferenças nos campos comparados."
    categories: dict[str, int] = {}
    for row in differences:
        categories[row.category] = categories.get(row.category, 0) + 1
    category_text = ", ".join(f"{key} ({value})" for key, value in categories.items())
    return (
        f"Foram identificadas {len(differences)} diferenças ou lacunas nas categorias {category_text}. "
        "A comparação é um apoio à análise e deve ser revisada contra o texto original "
        "das apólices; não constitui parecer jurídico."
    )


def _compare_values(a: PolicyFact, b: PolicyFact) -> tuple[str, str]:
    """Classifica o par de fatos: ausência, ambiguidade, igualdade ou diferença."""
    if a.status == "not_found" and b.status == "not_found":
        return "ambos_ausentes", "Campo não localizado nos dois documentos"
    if a.status == "not_found":
        return "ausente_em_a", "Campo localizado somente na apólice B"
    if b.status == "not_found":
        return "ausente_em_b", "Campo localizado somente na apólice A"
    if a.status == "ambiguous" or b.status == "ambiguous":
        return "ambigua", "Requer revisão humana por ambiguidade na extração"
    if a.normalized_value == b.normalized_value:
        return "igual", "Valores equivalentes no texto normalizado"
    return "diferente", "Valores ou condições diferentes"


def _not_found(document_id: str, key: tuple[str, str]) -> PolicyFact:
    """Cria o fato sentinela de ausência para um campo não extraído."""
    return PolicyFact(document_id, key[0], key[1], None, "not_found", 0.0, None, "Informação não localizada.")
