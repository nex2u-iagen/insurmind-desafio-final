"""Persistência de chaves e modelos digitados no front — arquivo ``.env`` (fora do git).

Grava/atualiza variáveis por provedor sem apagar o resto do arquivo (``set_key``)
e com permissão ``0600`` (somente dono). O caminho pode ser sobrescrito pela
variável ``SEGURAMENTE_ENV_FILE`` (testes e ambientes separados).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import dotenv_values, set_key

from .base import PROVEDORES

logger = logging.getLogger(__name__)

PASTA_RAIZ = Path(__file__).resolve().parents[2]


def caminho_env() -> Path:
    """Caminho do ``.env`` ativo (override via ``SEGURAMENTE_ENV_FILE``)."""
    return Path(os.getenv("SEGURAMENTE_ENV_FILE", "") or PASTA_RAIZ / ".env")


def _variaveis_do_provedor(provedor: str) -> tuple[str, str]:
    """Par ``(variável de chave, variável de modelo)`` do provedor registrado."""
    classe = PROVEDORES[provedor]
    return classe.variavel_chave, classe.variavel_modelo


def gravar_chaves(provedor: str, modelo: str | None = None, api_key: str | None = None) -> Path:
    """Grava/atualiza chave e modelo do provedor no ``.env`` (valores vazios são ignorados).

    Args:
        provedor: Nome registrado (``openai``, ``groq`` ou ``google``).
        modelo: Modelo a persistir (``<PROVEDOR>_MODEL``); ignorado se vazio.
        api_key: Chave a persistir (``<PROVEDOR>_API_KEY``); ignorada se vazia.

    Returns:
        Caminho do arquivo ``.env``.

    Raises:
        KeyError: Provedor não registrado.
    """
    if provedor not in PROVEDORES:
        raise KeyError(f"Provedor desconhecido: {provedor}")
    var_chave, var_modelo = _variaveis_do_provedor(provedor)
    chave = (api_key or "").strip()
    modelo_efetivo = (modelo or "").strip()
    caminho = caminho_env()
    if not chave and not modelo_efetivo:
        return caminho
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if not caminho.exists():
        caminho.touch()
    if chave:
        set_key(str(caminho), var_chave, chave)
    if modelo_efetivo:
        set_key(str(caminho), var_modelo, modelo_efetivo)
    try:
        caminho.chmod(0o600)
    except OSError:  # pragma: no cover — best effort (ex.: FS sem POSIX)
        logger.debug("Não foi possível aplicar permissão 0600 em %s.", caminho)
    return caminho


def chaves_salvas() -> dict[str, str]:
    """Valores (não vazios) já presentes no ``.env`` ativo."""
    return {chave: valor for chave, valor in dotenv_values(caminho_env()).items() if valor}


def valores_do_provedor(provedor: str) -> dict[str, str]:
    """Chave/modelo salvos do provedor para pré-preencher o front.

    Para ``openai`` também consulta ``SEGURAMENTE_LLM_MODEL`` (variável de compat).
    """
    var_chave, var_modelo = _variaveis_do_provedor(provedor)
    salvas = chaves_salvas()
    modelo = salvas.get(var_modelo, "")
    if provedor == "openai" and not modelo:
        modelo = salvas.get("SEGURAMENTE_LLM_MODEL", "")
    return {"api_key": salvas.get(var_chave, ""), "modelo": modelo}
