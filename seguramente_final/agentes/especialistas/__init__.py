"""Especialistas — um módulo individual por área de domínio das apólices D&O."""

from __future__ import annotations

from ...motor_llm.base import ChatJson
from .base import EspecialistaNode
from .coberturas import EspecialistaCoberturas
from .condicoes import EspecialistaCondicoes
from .exclusoes import EspecialistaExclusoes
from .extensoes import EspecialistaExtensoes
from .identificacao import EspecialistaIdentificacao
from .limites import EspecialistaLimites

CLASSES_ESPECIALISTAS: tuple[type[EspecialistaNode], ...] = (
    EspecialistaIdentificacao,
    EspecialistaLimites,
    EspecialistaCoberturas,
    EspecialistaExtensoes,
    EspecialistaExclusoes,
    EspecialistaCondicoes,
)

NOMES_ESPECIALISTAS: tuple[str, ...] = tuple(classe.nome for classe in CLASSES_ESPECIALISTAS)


def criar_especialistas(cliente: ChatJson | None = None) -> dict[str, EspecialistaNode]:
    """Fabrica uma instância de cada especialidade, com cliente LLM opcional."""
    return {classe.nome: classe(cliente=cliente) for classe in CLASSES_ESPECIALISTAS}


__all__ = [
    "CLASSES_ESPECIALISTAS",
    "NOMES_ESPECIALISTAS",
    "EspecialistaCoberturas",
    "EspecialistaCondicoes",
    "EspecialistaExclusoes",
    "EspecialistaExtensoes",
    "EspecialistaIdentificacao",
    "EspecialistaLimites",
    "EspecialistaNode",
    "criar_especialistas",
]
