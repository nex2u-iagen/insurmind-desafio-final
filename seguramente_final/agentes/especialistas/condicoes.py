"""Especialista em condições, deveres e obrigações do segurado."""

from __future__ import annotations

from ..registro import agente
from .base import EspecialistaNode

PROMPT_SISTEMA = (
    "Você é o especialista em condições, deveres e obrigações do segurado de apólices D&O. "
    "Analise SOMENTE a sua fatia de fatos (condições, deveres e obrigações) e responda SOMENTE JSON: "
    '{"veredito": "uma frase técnica"}'
)


@agente(rotulo="Condições", ordem=80)
class EspecialistaCondicoes(EspecialistaNode):
    """Especialista em condições, deveres e obrigações do segurado."""

    nome = "condicoes"
    categorias = frozenset({"condicoes"})
    foco = "condições, deveres e obrigações do segurado"
    prompt_sistema = PROMPT_SISTEMA
