"""Especialista em identificação da apólice — seguradora, vigência e âmbito."""

from __future__ import annotations

from ..registro import agente
from .base import EspecialistaNode

PROMPT_SISTEMA = (
    "Você é o especialista em identificação da apólice: seguradora, vigência e âmbito geográfico "
    "de apólices D&O. Analise SOMENTE a sua fatia de fatos (identificação) e responda SOMENTE JSON: "
    '{"veredito": "uma frase técnica"}'
)


@agente(rotulo="Identificação", ordem=30)
class EspecialistaIdentificacao(EspecialistaNode):
    """Especialista em identificação da apólice: seguradora, vigência e âmbito."""

    nome = "identificacao"
    categorias = frozenset({"identificacao"})
    foco = "identificação da apólice: seguradora, vigência e âmbito geográfico"
    prompt_sistema = PROMPT_SISTEMA
