"""Especialista em exclusões e ressalvas contratuais."""

from __future__ import annotations

from ..registro import agente
from .base import EspecialistaNode

PROMPT_SISTEMA = (
    "Você é o especialista em exclusões e ressalvas contratuais de apólices D&O. "
    "Analise SOMENTE a sua fatia de fatos (exclusões e ressalvas) e responda SOMENTE JSON: "
    '{"veredito": "uma frase técnica"}'
)


@agente(rotulo="Exclusões", ordem=70)
class EspecialistaExclusoes(EspecialistaNode):
    """Especialista em exclusões e ressalvas contratuais."""

    nome = "exclusoes"
    categorias = frozenset({"exclusoes"})
    foco = "exclusões e ressalvas contratuais"
    prompt_sistema = PROMPT_SISTEMA
