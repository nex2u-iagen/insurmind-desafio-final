"""Contrato do motor LLM — provedores, registry e fábrica."""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Protocol

import requests

logger = logging.getLogger(__name__)

TOKENS_MAX = 4096
TIMEOUT_PADRAO = 60

STATUS_TRANSITORIOS = frozenset({429, 500, 502, 503, 504})
TENTATIVAS_PADRAO = 5
ESPERA_BASE = 1.0
ESPERA_MAX = 8.0
ESPERA_JITTER = 0.15
RETRY_AFTER_MAX = 30.0

# Rajadas de 429/503 nascem de chamadas paralelas (fan-out de especialistas).
# O semáforo global limita quantas requisições trafegam ao mesmo tempo no
# processo; o backoff/jitter cuidam do espaçamento entre tentativas.
CONCORRENCIA_PADRAO = 2
VARIAVEL_CONCORRENCIA = "SEGURAMENTE_LLM_CONCORRENCIA"

_bloqueio_limiter = threading.Lock()
_limiter: threading.Semaphore | None = None


def concorrencia_llm() -> int:
    """Limite de requisições LLM simultâneas no processo (env, default 2)."""
    bruto = os.getenv(VARIAVEL_CONCORRENCIA, str(CONCORRENCIA_PADRAO))
    try:
        return max(1, int(bruto))
    except ValueError:
        logger.warning("Valor inválido em %s (%r); usando %s.", VARIAVEL_CONCORRENCIA, bruto, CONCORRENCIA_PADRAO)
        return CONCORRENCIA_PADRAO


def _limitador() -> threading.Semaphore:
    """Semáforo global lazy (uma instância por processo)."""
    global _limiter
    with _bloqueio_limiter:
        if _limiter is None:
            _limiter = threading.Semaphore(concorrencia_llm())
        return _limiter


def reiniciar_limitador() -> None:
    """Recria o semáforo (testes e troca de ``SEGURAMENTE_LLM_CONCORRENCIA``)."""
    global _limiter
    with _bloqueio_limiter:
        _limiter = None


def _espera_de_retry(resposta: Any, backoff: float, aleatorio: Any) -> float:
    """Backoff exponencial com jitter, honrando ``Retry-After`` quando presente.

    Args:
        resposta: Resposta transitória (pode não ter cabeçalhos em stubs).
        backoff: Espera base calculada (``ESPERA_BASE * 2^n``, já com cap).
        aleatorio: Função ``U[0, 1)`` do jitter (injetável nos testes).

    Returns:
        Espera final em segundos (limitada a ``RETRY_AFTER_MAX``).
    """
    espera = backoff + ESPERA_JITTER * backoff * aleatorio()
    retry_after = _retry_after(resposta)
    if retry_after is not None:
        espera = max(espera, retry_after)
    return min(espera, RETRY_AFTER_MAX)


def _retry_after(resposta: Any) -> float | None:
    """Lê ``Retry-After`` (segundos) da resposta; ignora formatos não numéricos."""
    cabecalhos = getattr(resposta, "headers", None) or {}
    bruto = cabecalhos.get("Retry-After") if hasattr(cabecalhos, "get") else None
    if bruto is None:
        return None
    try:
        segundos = float(str(bruto).strip())
    except ValueError:
        return None
    return max(0.0, segundos)


def enviar_post(
    post: Any,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json: dict[str, Any] | None = None,
    timeout: int | None = None,
    tentativas: int = TENTATIVAS_PADRAO,
    dormir: Any = None,
    aleatorio: Any = None,
    nao_repetir: Any = None,
) -> Any:
    """POST com retry limitado somente para falhas transitórias.

    Repete em ``Timeout``/``ConnectionError`` e status ``{429, 500, 502, 503,
    504}`` com backoff exponencial (``1 * 2^n``, limitado a ``ESPERA_MAX``) +
    jitter proporcional, honrando ``Retry-After``. Erros permanentes (ex.:
    400) saem na primeira chamada. Cada requisição atravessa o semáforo
    global (:func:`concorrencia_llm`) — as esperas de backoff não seguram
    vaga. A mensagem crua da exceção nunca é registrada aqui (a URL pode
    conter credencial); o provedor formata e redige o erro final.

    Args:
        post: Transporte HTTP (``requests.post`` ou stub de teste).
        url: Destino da requisição.
        headers: Cabeçalhos da requisição.
        json: Payload JSON.
        timeout: Timeout em segundos.
        tentativas: Total de tentativas (mínimo 1).
        dormir: Injeção de espera para testes; default ``time.sleep``.
        aleatorio: Injeção de ``U[0, 1)`` do jitter para testes.
        nao_repetir: Predicado ``(resposta) -> bool``; quando verdadeiro a
            resposta transitória não é repetida (ex.: cota estourada que só
            volta em horas — repetir só atrasaria o fallback offline).

    Returns:
        Resposta HTTP com status < 400.

    Raises:
        requests.HTTPError: Status permanente ou transitório esgotado.
        requests.Timeout | requests.ConnectionError: Transporte esgotado.
    """
    dormir = dormir or time.sleep
    aleatorio = aleatorio or random.random
    max_tentativas = max(tentativas, 1)
    ultimo_erro: requests.RequestException | None = None
    resposta: Any = None
    limiter = _limitador()
    for tentativa in range(1, max_tentativas + 1):
        try:
            with limiter:
                resposta = post(url, headers=headers, json=json, timeout=timeout)
        except (requests.Timeout, requests.ConnectionError) as exc:
            ultimo_erro = exc
            logger.info("POST transitório %s (tentativa %s/%s)", type(exc).__name__, tentativa, max_tentativas)
        else:
            if resposta.status_code < 400:
                return resposta
            if resposta.status_code not in STATUS_TRANSITORIOS:
                resposta.raise_for_status()
            ultimo_erro = None
            logger.info("POST status %s transitório (tentativa %s/%s)", resposta.status_code, tentativa, max_tentativas)
            if nao_repetir is not None and nao_repetir(resposta):
                logger.info(
                    "POST status %s não será repetido (decisão do provedor, ex.: cota esgotada).",
                    resposta.status_code,
                )
                break
        if tentativa < max_tentativas:
            backoff = min(ESPERA_BASE * (2 ** (tentativa - 1)), ESPERA_MAX)
            dormir(_espera_de_retry(resposta, backoff, aleatorio))
    if ultimo_erro is not None:
        raise ultimo_erro
    resposta.raise_for_status()
    return resposta


class LLMError(RuntimeError):
    """Erro controlado de integração com modelo de linguagem."""


class ChatJson(Protocol):
    """Contrato mínimo compartilhado por extrator, resumidor e especialistas."""

    def chat_json(self, messages: list[dict[str, str]], *, temperature: float = 0.1) -> dict[str, Any]:
        """Envia mensagens e retorna o objeto JSON decodificado."""
        ...


PROVEDORES: dict[str, type[ProvedorLLM]] = {}


def registrar_provedor(nome: str):
    """Registra uma classe de provedor no registry global (registry + decorator)."""

    def decorador(classe: type[ProvedorLLM]) -> type[ProvedorLLM]:
        PROVEDORES[nome] = classe
        classe.nome = nome
        classe.variavel_modelo = f"{nome.upper()}_MODEL"
        return classe

    return decorador


def provedores_disponiveis() -> list[str]:
    """Nomes dos provedores registrados em ordem estável."""
    return sorted(PROVEDORES)


def criar_cliente(
    provedor: str,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: int | None = None,
    post: Any = None,
) -> ProvedorLLM:
    """Instancia o provedor pelo nome (fábrica do registry).

    Args:
        provedor: ``openai``, ``groq`` ou ``google``.
        model: Modelo específico; usa o default do provedor quando ausente.
        api_key: Chave vinda do front; usa a variável de ambiente quando ausente.
        base_url: Sobrescreve a base do provedor (proxies).
        timeout: Timeout em segundos.
        post: Transporte HTTP injetável (testes sem rede).

    Returns:
        Instância de :class:`ProvedorLLM`.

    Raises:
        LLMError: Provedor não registrado.
    """
    if provedor not in PROVEDORES:
        raise LLMError(f"Provedor desconhecido: {provedor}. Disponíveis: {', '.join(provedores_disponiveis())}")
    classe = PROVEDORES[provedor]
    return classe(api_key=api_key, model=model, base_url=base_url, timeout=timeout, post=post)


class ProvedorLLM(ABC):
    """Base dos provedores: resolve credenciais/modelo e declara o contrato JSON."""

    nome = "base"
    modelo_padrao: str
    base_url_padrao: str
    variavel_chave: str
    variavel_chave_secundaria: str | None = None
    variavel_modelo: str | None = None  # definida pelo registrar_provedor

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: int | None = None,
        post: Any = None,
    ) -> None:
        self.api_key = api_key or self._chave_do_ambiente()
        self.model = model or os.getenv(self.variavel_modelo or "", "") or self.modelo_padrao
        self.base_url = (base_url or self.base_url_padrao).rstrip("/")
        self.timeout = timeout or int(os.getenv("SEGURAMENTE_LLM_TIMEOUT", str(TIMEOUT_PADRAO)))
        self._post = post or requests.post

    def _chave_do_ambiente(self) -> str:
        chave = os.getenv(self.variavel_chave, "")
        if not chave and self.variavel_chave_secundaria:
            chave = os.getenv(self.variavel_chave_secundaria, "")
        return chave

    @abstractmethod
    def chat_json(self, messages: list[dict[str, str]], *, temperature: float = 0.1) -> dict[str, Any]:
        """Chama o modelo e decodifica a resposta JSON."""
        ...
