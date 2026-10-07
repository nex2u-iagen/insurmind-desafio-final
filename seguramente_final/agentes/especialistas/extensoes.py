"""Especialista em extensões e endossos contratuais."""

from __future__ import annotations

from ..registro import agente
from .base import EspecialistaNode

PROMPT_SISTEMA = (
    "Você é o especialista em extensões e endossos (investigação, subsidiárias, período adicional) "
    "de apólices D&O. Analise SOMENTE a sua fatia de fatos (extensões e endossos) e responda SOMENTE JSON: "
    '{"veredito": "uma frase técnica"}'
)


@agente(rotulo="Extensões", ordem=60)
class EspecialistaExtensoes(EspecialistaNode):
    """Especialista em extensões e endossos contratuais."""

    nome = "extensoes"
    categorias = frozenset({"extensoes"})
    foco = "extensões e endossos (investigação, subsidiárias, período adicional)"
    prompt_sistema = PROMPT_SISTEMA
