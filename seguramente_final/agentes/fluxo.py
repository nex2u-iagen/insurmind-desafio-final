"""Fluxo declarativo do grafo — ordem das etapas, contexto e fábrica dos agentes.

`FLUXO` descreve a linha principal; :data:`FANOUT` marca o ponto em que só os
especialistas do plano do supervisor rodam em paralelo. O `grafo.py` itera
essa sequência — criar um agente novo = classe decorada + linha no fluxo.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .gate import GateHumano
from .nodes import ExtratorNode, IngestorNode, PersistidorNode, SintetizadorNode
from .registro import agente_por_etapa
from .supervisor import SupervisorAbertura


class _SentinelaFanOut:
    """Marca o ponto de fan-out dos especialistas dentro de ``FLUXO``."""

    def __repr__(self) -> str:
        return "FANOUT"


FANOUT = _SentinelaFanOut()
FluxoItem = str | _SentinelaFanOut

FLUXO: tuple[FluxoItem, ...] = (
    "supervisor_abertura",
    "ingestar",
    "extrair",
    FANOUT,
    "comparar",
    "revisor",
    "gate",
    "sintetizar",
    "supervisor_encerramento",
    "persistir",
)


@dataclass(frozen=True)
class Contexto:
    """Dependências injetadas na construção dos agentes (composition root)."""

    cliente: Any = None
    extrator: Any = None
    diretorio: Path = Path("data")
    memoria: Any = None


FABRICAS: dict[str, Callable[[Contexto], Any]] = {
    "supervisor_abertura": lambda ctx: SupervisorAbertura(ctx.cliente, ctx.memoria),
    "ingestar": lambda ctx: IngestorNode(ctx.memoria),
    "extrair": lambda ctx: ExtratorNode(ctx.extrator),
    "gate": lambda ctx: GateHumano(ctx.diretorio / "evidence"),
    "sintetizar": lambda ctx: SintetizadorNode(ctx.cliente),
    "persistir": lambda ctx: PersistidorNode(ctx.diretorio / "policies.db", ctx.memoria),
}


def construir(etapa: str, ctx: Contexto) -> Any:
    """Instancia o agente da etapa (fábrica explícita ou classe registrada)."""
    fabrica = FABRICAS.get(etapa)
    if fabrica is not None:
        return fabrica(ctx)
    classe = agente_por_etapa(etapa).classe
    if etapa.startswith("especialista_"):
        return classe(cliente=ctx.cliente, memoria=ctx.memoria)
    return classe()


def validar_fluxo(fluxo: Sequence[FluxoItem]) -> None:
    """Valida a sequência: etapas sem duplicar e um único FANOUT no meio."""
    lineares = [item for item in fluxo if item is not FANOUT]
    if len(set(lineares)) != len(lineares):
        raise ValueError("FLUXO contém etapa duplicada.")
    marcas = [indice for indice, item in enumerate(fluxo) if item is FANOUT]
    if len(marcas) != 1:
        raise ValueError(f"FLUXO deve conter exatamente um FANOUT (encontrou {len(marcas)}).")
    if marcas[0] in (0, len(fluxo) - 1):
        raise ValueError("FANOUT não pode ser a primeira nem a última posição do FLUXO.")
