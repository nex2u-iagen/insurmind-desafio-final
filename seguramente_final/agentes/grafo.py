"""Montagem do grafo LangGraph — itera o fluxo declarativo e o registro de agentes."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from ..storage import PolicyStore
from ..telemetria import com_evento
from .checkpoint_epoch import EpochDBCheckpointer
from .estado import EstadoAnalise
from .fluxo import FANOUT, FLUXO, Contexto, construir, validar_fluxo
from .memoria import criar_memoria
from .registro import agentes_registrados

logger = logging.getLogger(__name__)


def montar_grafo(
    *,
    extrator: Any,
    cliente: Any = None,
    diretorio: str | Path = "data",
    provider_mode: str = "offline",
) -> Any:
    """Compila o grafo LangGraph com checkpointer filesystem e memória.

    Args:
        extrator: Estratégia de extração de fatos (injetável).
        cliente: Cliente LLM opcional usado por especialistas e sintetizador.
        diretorio: Raiz de dados (checkpoints, evidence, memoria, policies.db).
        provider_mode: ``offline`` ignora o cliente LLM dos sub-agentes.

    Returns:
        Grafo compilado (``CompiledStateGraph``).
    """
    validar_fluxo(FLUXO)
    diretorio = Path(diretorio)
    memoria = criar_memoria(diretorio / "memoria")
    cliente_efetivo = cliente if provider_mode != "offline" else None
    ctx = Contexto(cliente=cliente_efetivo, extrator=extrator, diretorio=diretorio, memoria=memoria)

    especialistas = [registro.etapa for registro in agentes_registrados() if registro.etapa.startswith("especialista_")]
    lineares = [item for item in FLUXO if item is not FANOUT]

    grafo = StateGraph(EstadoAnalise)
    for etapa in [*lineares, *especialistas]:
        grafo.add_node(etapa, com_evento(etapa, construir(etapa, ctx)))

    def _rotear_especialistas(state: dict[str, Any]) -> list[str]:
        """Fan-out condicional: só os especialistas do plano do supervisor."""
        plano = state.get("plano") or [etapa.removeprefix("especialista_") for etapa in especialistas]
        planejados = [f"especialista_{nome}" for nome in plano if f"especialista_{nome}" in especialistas]
        return planejados or especialistas

    rota = {etapa: etapa for etapa in especialistas}
    pendentes: list[str] = [START]
    for item in FLUXO:
        if item is FANOUT:
            if len(pendentes) != 1:
                raise ValueError("FANOUT exige um único etapa de origem no FLUXO.")
            grafo.add_conditional_edges(pendentes[0], _rotear_especialistas, rota)
            pendentes = list(especialistas)
        else:
            for origem in pendentes:
                grafo.add_edge(origem, item)
            pendentes = [item]
    for origem in pendentes:
        grafo.add_edge(origem, END)

    checkpointer = EpochDBCheckpointer(storage_dir=diretorio)
    compilado = grafo.compile(checkpointer=checkpointer)
    logger.info("Grafo compilado: provider=%s, diretorio=%s", provider_mode, diretorio)
    return compilado


def _store(diretorio: str | Path) -> PolicyStore:
    """Abre o store local (uso explícito fora do grafo, se necessário)."""
    return PolicyStore(Path(diretorio) / "policies.db")
