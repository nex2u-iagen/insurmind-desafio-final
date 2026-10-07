"""Contrato de agente — papel, prompt system e ferramentas permitidas.

O :class:`ContratoAgente` é a declaração estática de cada agente da orquestra:
quem é (``nome``/``papel``), o que diz ao modelo (``prompt_sistema``) e quais
ferramentas da allowlist pode acionar (``ferramentas``). O dispatcher
:func:`seguramente_final.tools.executar_ferramenta` usa o contrato para impor
permissão de ferramenta no fluxo real (defesa em profundidade além da
allowlist imposta em código).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..tools.registry import ALLOWLIST


@dataclass(frozen=True)
class ContratoAgente:
    """Contrato declarativo e imutável de um agente da orquestra.

    Attributes:
        nome: Identificador estável (id da etapa no grafo).
        papel: Papel do agente em uma frase.
        prompt_sistema: System prompt declarado (visível no front).
        ferramentas: Subconjunto da allowlist que o agente pode acionar.
    """

    nome: str
    papel: str
    prompt_sistema: str
    ferramentas: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        """Valida campos não vazios e ferramentas dentro da allowlist."""
        if not self.nome.strip():
            raise ValueError("ContratoAgente exige 'nome' não vazio.")
        if not self.papel.strip():
            raise ValueError(f"ContratoAgente {self.nome!r}: 'papel' não pode ser vazio.")
        if not self.prompt_sistema.strip():
            raise ValueError(f"ContratoAgente {self.nome!r}: 'prompt_sistema' não pode ser vazio.")
        object.__setattr__(self, "ferramentas", frozenset(self.ferramentas))
        fora_da_allowlist = self.ferramentas - ALLOWLIST
        if fora_da_allowlist:
            raise ValueError(
                f"ContratoAgente {self.nome!r}: ferramentas fora da allowlist: {sorted(fora_da_allowlist)}"
            )
