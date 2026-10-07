"""Registry de ferramentas dos sub-agentes — registro por decorator, allowlist e dispatcher."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from ..telemetria import evento_ferramenta, origem_agente

logger = logging.getLogger(__name__)

ALLOWLIST = frozenset({"ingestar_documentos", "comparar_apolices", "resumir_comparacao", "extrair_texto_ocr"})


class AgenteFerramentas(Protocol):
    """Estrutura mínima que o dispatcher exige de um agente (duck typing)."""

    nome: str
    ferramentas: frozenset[str]


@dataclass(frozen=True)
class Ferramenta:
    """Ferramenta registrada: nome, descrição e função executável."""

    nome: str
    descricao: str
    funcao: Callable[..., Any]


_REGISTRADOR: dict[str, Ferramenta] = {}


def registrar_ferramenta(nome: str, descricao: str):
    """Registra uma função como ferramenta do agente (com telemetria automática)."""

    def decorador(funcao: Callable[..., Any]) -> Callable[..., Any]:
        def publicada(*args: Any, **kwargs: Any) -> Any:
            with evento_ferramenta(nome):
                return funcao(*args, **kwargs)

        publicada.__name__ = funcao.__name__
        publicada.__doc__ = funcao.__doc__
        _REGISTRADOR[nome] = Ferramenta(nome=nome, descricao=descricao, funcao=publicada)
        return publicada

    return decorador


def listar_ferramentas() -> list[str]:
    """Nomes das ferramentas registradas, em ordem estável."""
    return sorted(_REGISTRADOR)


def obter_ferramenta(nome: str) -> Ferramenta:
    """Recupera uma ferramenta validando a allowlist imposta em código.

    Args:
        nome: Nome da ferramenta.

    Returns:
        A :class:`Ferramenta` registrada.

    Raises:
        KeyError: Ferramenta não registrada.
        RuntimeError: Fora da allowlist.
    """
    if nome not in ALLOWLIST:
        logger.warning("Tentativa de ferramenta fora da allowlist: %s", nome)
        raise RuntimeError(f"Ferramenta fora da allowlist: {nome}")
    if nome not in _REGISTRADOR:
        raise KeyError(f"Ferramenta não registrada: {nome}")
    return _REGISTRADOR[nome]


def executar_ferramenta(agente: AgenteFerramentas, nome: str, *args: Any, **kwargs: Any) -> Any:
    """Aciona uma ferramenta em nome de um agente validando permissão e allowlist.

    É o único caminho de chamada que respeita o contrato do agente: a
    permissão (``nome ∈ agente.ferramentas``) é imposta antes da allowlist de
    código, e a origem do agente é publicada junto com o evento da ferramenta.

    Args:
        agente: Contrato do agente (``nome`` + ``ferramentas``).
        nome: Nome da ferramenta registrada.
        *args: Argumentos posicionais da ferramenta.
        **kwargs: Argumentos nomeados da ferramenta.

    Returns:
        O retorno da ferramenta.

    Raises:
        PermissionError: Ferramenta fora das ferramentas do contrato do agente.
        RuntimeError: Ferramenta fora da allowlist imposta em código.
        KeyError: Ferramenta não registrada.
    """
    if nome not in agente.ferramentas:
        logger.warning("Agente %s sem permissão para a ferramenta %s", agente.nome, nome)
        raise PermissionError(f"Agente '{agente.nome}' não pode acionar '{nome}' (fora do contrato).")
    ferramenta = obter_ferramenta(nome)
    with origem_agente(agente.nome):
        return ferramenta.funcao(*args, **kwargs)
