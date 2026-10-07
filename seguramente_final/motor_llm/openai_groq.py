"""Provedores compatíveis com a API REST da OpenAI (usada por openai e groq)."""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

from .base import TOKENS_MAX, LLMError, ProvedorLLM, enviar_post

logger = logging.getLogger(__name__)


class ProvedorOpenAICompativel(ProvedorLLM):
    """Implementa ``chat_json`` no formato ``/chat/completions`` da OpenAI."""

    def chat_json(self, messages: list[dict[str, str]], *, temperature: float = 0.1) -> dict[str, Any]:
        if not self.api_key:
            raise LLMError(f"{self.variavel_chave} não configurada para o provedor {self.nome}.")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": temperature,
        }
        if self.model.startswith("gpt-5"):
            payload["max_completion_tokens"] = TOKENS_MAX
        else:
            payload["max_tokens"] = TOKENS_MAX
        try:
            response = enviar_post(
                self._post,
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=self.timeout,
            )
            data = response.json()
        except requests.RequestException as exc:
            logger.warning(
                "Falha HTTP no provedor %s modelo %s: %s: %s", self.nome, self.model, type(exc).__name__, exc
            )
            raise LLMError(f"Falha na chamada ao modelo {self.model}: {exc}") from exc
        if "error" in data:
            raise LLMError(f"Provedor {self.nome} retornou erro: {data['error']}")
        choices = data.get("choices") or []
        if not choices:
            raise LLMError(f"Provedor {self.nome} não retornou choices: {str(data)[:1000]}")
        try:
            content = json.loads(choices[0]["message"]["content"])
        except (ValueError, KeyError, TypeError) as exc:
            raise LLMError(f"Resposta do modelo {self.model} não é JSON válido: {exc}") from exc
        usage = data.get("usage") or {}
        logger.info(
            "llm chamada provedor=%s modelo=%s tokens_entrada=%s tokens_saida=%s",
            self.nome,
            self.model,
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
        )
        return content


class ProvedorOpenAI(ProvedorOpenAICompativel):
    """Provedor OpenAI oficial."""

    modelo_padrao = "gpt-5-mini"
    base_url_padrao = "https://api.openai.com/v1"
    variavel_chave = "OPENAI_API_KEY"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        if not kwargs.get("model"):
            # Compat: SEGURAMENTE_LLM_MODEL do .env continua valendo só para openai
            # (depois de OPENAI_MODEL, a variável nova por provedor).
            import os

            self.model = os.getenv("OPENAI_MODEL", "") or os.getenv("SEGURAMENTE_LLM_MODEL", "") or self.modelo_padrao


class ProvedorGroq(ProvedorOpenAICompativel):
    """Provedor Groq (API compatível com OpenAI, base dedicada)."""

    modelo_padrao = "llama-3.3-70b-versatile"
    base_url_padrao = "https://api.groq.com/openai/v1"
    variavel_chave = "GROQ_API_KEY"
