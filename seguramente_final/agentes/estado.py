"""Estado tipado do grafo de análise de apólices D&O."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from ..models import ComparisonRow, PolicyDocument


class EstadoAnalise(TypedDict, total=False):
    """Estado compartilhado pelos nós do LangGraph.

    Canais com reducer ``operator.add`` (``live_status``, ``achados``) aceitam
    escritas de nós paralelos; os demais têm escritor único por nó.
    """

    thread_id: str
    caminhos: list[str]
    nomes: list[str]
    pedido_usuario: str
    provedor: str
    modelo: str
    simular_ocr: bool
    plano: list[str]
    instrucoes: dict[str, str]
    memoria_contexto: list[str]
    documentos: list[dict[str, Any]]
    indexacao_documental: dict[str, Any]
    fatos: list[dict[str, Any]]
    estatisticas_extracao: list[dict[str, Any]]
    comparacao: list[dict[str, Any]]
    pontos: list[dict[str, Any]]
    decisao_humana: dict[str, Any]
    resumo: str
    mensagem_supervisor: str
    fallback_extrator: bool
    fallback_resumo: bool
    motivo_degradacao: str
    live_status: Annotated[list[dict[str, Any]], operator.add]
    achados: Annotated[list[dict[str, Any]], operator.add]


def novo_status(etapa: str, agente: str, detalhe: str = "", status: str = "ok") -> dict[str, str]:
    """Cria uma entrada do trace de execução (live_status)."""
    return {"etapa": etapa, "agente": agente, "detalhe": detalhe, "status": status}


def adicionar_live_status(estado: dict[str, Any], entradas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Concatena entradas ao trace sem mutar a lista original do estado."""
    anteriores = estado.get("live_status") or []
    return [*anteriores, *entradas]


def serializar_documento(documento: PolicyDocument) -> dict[str, Any]:
    """Converte :class:`PolicyDocument` em dict JSON-safe para o estado."""
    return documento.to_dict()


def reidratar_documento(dados: dict[str, Any]) -> PolicyDocument:
    """Reconstrói :class:`PolicyDocument` a partir do estado."""
    return PolicyDocument.from_dict(dados)


def reidratar_linha(alvo: dict[str, Any] | ComparisonRow) -> ComparisonRow:
    """Aceita dict serializado ou instância de :class:`ComparisonRow`."""
    return alvo if isinstance(alvo, ComparisonRow) else ComparisonRow(**alvo)
