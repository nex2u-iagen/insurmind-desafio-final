"""Blocos de contexto reutilizáveis na montagem de prompts dos agentes.

Módulo de raiz (sem dependências) para ser consumido por ``agentes`` e
``tools`` sem criar ciclos de importação.
"""

from __future__ import annotations

LIMITE_LEMBRANCA = 500
MAX_LEMBRANCAS = 3


def bloco_memoria(memoria_contexto: list[str] | None) -> str:
    """Formata as lembranças de análises anteriores para o prompt.

    Args:
        memoria_contexto: Textos recuperados da memória (já truncados na origem
            ou não); vazio/``None`` devolve ``""``.

    Returns:
        Bloco ``"Análises anteriores (memória):"`` com no máximo
        :data:`MAX_LEMBRANCAS` itens de :data:`LIMITE_LEMBRANCA` caracteres.
    """
    if not memoria_contexto:
        return ""
    linhas = [f"- {str(texto)[:LIMITE_LEMBRANCA]}" for texto in memoria_contexto[:MAX_LEMBRANCAS]]
    return "Análises anteriores (memória):\n" + "\n".join(linhas)
