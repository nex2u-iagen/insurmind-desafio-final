"""Especialista em coberturas D&O — A, B, C e custos de defesa."""

from __future__ import annotations

from ..registro import agente
from .base import EspecialistaNode

PROMPT_SISTEMA = (
    "Você é o especialista em coberturas D&O (A, B, C) e custos de defesa de apólices D&O. "
    "Analise SOMENTE a sua fatia de fatos (coberturas A, B, C e custos de defesa) e responda SOMENTE JSON: "
    '{"veredito": "uma frase técnica"}'
)


@agente(rotulo="Coberturas", ordem=50)
class EspecialistaCoberturas(EspecialistaNode):
    """Especialista em coberturas D&O (A, B, C) e custos de defese."""

    nome = "coberturas"
    categorias = frozenset({"coberturas"})
    foco = "coberturas D&O (A, B, C) e custos de defesa"
    prompt_sistema = PROMPT_SISTEMA
