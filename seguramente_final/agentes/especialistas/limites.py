"""Especialista em limites de responsabilidade, franquias e retenções."""

from __future__ import annotations

from ..registro import agente
from .base import EspecialistaNode

PROMPT_SISTEMA = (
    "Você é o especialista em limites de responsabilidade, franquias e retenções de apólices D&O. "
    "Analise SOMENTE a sua fatia de fatos (limites, franquias, retenções) e responda SOMENTE JSON: "
    '{"veredito": "uma frase técnica"}'
)


@agente(rotulo="Limites", ordem=40)
class EspecialistaLimites(EspecialistaNode):
    """Especialista em limites de responsabilidade, franquias e retenções."""

    nome = "limites"
    categorias = frozenset({"limites", "retencoes"})
    foco = "limites de responsabilidade, franquias e retenções"
    prompt_sistema = PROMPT_SISTEMA
