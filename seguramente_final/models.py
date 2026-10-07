"""Modelos de domínio do Projeto Final D&O (value objects imutáveis em uso)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

FactStatus = Literal["present", "not_found", "ambiguous", "not_applicable"]


@dataclass
class DocumentPage:
    """Página ingenefada de um documento, com texto e método de extração."""

    document_id: str
    page_number: int
    text: str
    extraction_method: str


@dataclass
class PolicyFact:
    """Fato estruturado extraído de uma apólice, com evidência e página de origem."""

    document_id: str
    category: str
    label: str
    value: str | None
    status: FactStatus
    confidence: float
    page: int | None
    evidence: str
    normalized_value: str | None = None
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serializa o fato para dicionário (JSON-friendly)."""
        return asdict(self)


@dataclass
class PolicyDocument:
    """Documento ingestado: identidade, páginas e fatos extraídos."""

    document_id: str
    name: str
    path: str
    source: str
    pages: list[DocumentPage] = field(default_factory=list)
    facts: list[PolicyFact] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serializa o documento para dicionário (JSON-friendly)."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PolicyDocument:
        """Reidrata um documento serializado (round-trip do estado do grafo)."""
        return cls(
            document_id=data["document_id"],
            name=data["name"],
            path=data["path"],
            source=data["source"],
            pages=[DocumentPage(**pagina) for pagina in data.get("pages", [])],
            facts=[PolicyFact(**fato) for fato in data.get("facts", [])],
        )


@dataclass
class ComparisonRow:
    """Linha da tabela comparativa: valores, status, diferença e evidências por página."""

    category: str
    label: str
    policy_a: str | None
    policy_b: str | None
    difference: str
    status: str
    evidence_a: str
    evidence_b: str
    page_a: int | None
    page_b: int | None

    def to_dict(self) -> dict[str, Any]:
        """Serializa a linha comparativa para dicionário (JSON-friendly)."""
        return asdict(self)


@dataclass
class AnalysisResult:
    """Resultado completo da análise: documentos, comparação, resumo e provider."""

    documents: list[PolicyDocument]
    comparison: list[ComparisonRow]
    executive_summary: str
    provider: str
    model: str
    fallback_offline: bool = False
    """``True`` quando a extração LLM falhou e as regras offline assumiram."""

    def to_dict(self) -> dict[str, Any]:
        """Serializa o resultado para dicionário (JSON-friendly), pronto para evidência."""
        return {
            "documents": [document.to_dict() for document in self.documents],
            "comparison": [row.to_dict() for row in self.comparison],
            "executive_summary": self.executive_summary,
            "provider": self.provider,
            "model": self.model,
            "fallback_offline": self.fallback_offline,
        }
