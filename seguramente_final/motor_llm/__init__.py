"""Motor LLM — provedores e síntese atrás de interface única (sem ferramentas)."""

from __future__ import annotations

from .base import (
    PROVEDORES,
    ChatJson,
    LLMError,
    ProvedorLLM,
    criar_cliente,
    provedores_disponiveis,
    registrar_provedor,
)
from .google import ProvedorGoogle
from .openai_groq import ProvedorGroq, ProvedorOpenAI

registrar_provedor("openai")(ProvedorOpenAI)
registrar_provedor("groq")(ProvedorGroq)
registrar_provedor("google")(ProvedorGoogle)

__all__ = [
    "PROVEDORES",
    "ChatJson",
    "LLMError",
    "ProvedorGoogle",
    "ProvedorGroq",
    "ProvedorLLM",
    "ProvedorOpenAI",
    "criar_cliente",
    "provedores_disponiveis",
    "registrar_provedor",
]
