"""Provedor Google (Gemini) — API ``generateContent`` com saída JSON."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

from .base import TOKENS_MAX, LLMError, ProvedorLLM, enviar_post

logger = logging.getLogger(__name__)

# "Please retry in 11h21.588535867s." — cota gratuita que só volta em horas.
_PADRAO_ESPERA_DA_COTA = re.compile(r"[Pp]lease retry in ([0-9.hms]+)")


def _corpo(resposta: Any) -> str:
    """Texto do corpo da resposta HTTP (vazio em stubs sem ``text``)."""
    texto = getattr(resposta, "text", None)
    return texto if isinstance(texto, str) else ""


def cota_esgotada(resposta: Any) -> bool:
    """True quando o 429 é de cota gratuita estourada (repetir não resolve).

    Diferente de um 429 de rajada (volta em segundos), a cota gratuita do
    Gemini zera o orçamento diário e pede espera de horas — repetir só
    atrasaria o fallback offline e o aviso de degradação no front.
    """
    corpo = _corpo(resposta)
    return "exceeded your current quota" in corpo or "RESOURCE_EXHAUSTED" in corpo


def _aviso_de_cota(exc: BaseException, chave: str) -> str:
    """Sufixo acionável na mensagem de erro quando a cota está no limite."""
    corpo = _corpo(getattr(exc, "response", None)).replace(chave, "***")
    if "exceeded your current quota" not in corpo:
        return ""
    espera = _PADRAO_ESPERA_DA_COTA.search(corpo)
    pista = f"; nova tentativa em ~{espera.group(1)}" if espera else ""
    return f" — cota gratuita do Google esgotada{pista}: troque GOOGLE_MODEL ou aguarde"


class ProvedorGoogle(ProvedorLLM):
    """Cliente do Gemini via ``.../models/{modelo}:generateContent``."""

    modelo_padrao = "gemini-3.5-flash"
    base_url_padrao = "https://generativelanguage.googleapis.com/v1beta"
    variavel_chave = "GOOGLE_API_KEY"
    variavel_chave_secundaria = "GEMINI_API_KEY"

    def chat_json(self, messages: list[dict[str, str]], *, temperature: float = 0.1) -> dict[str, Any]:
        if not self.api_key:
            raise LLMError(f"{self.variavel_chave} não configurada para o provedor google.")
        sistema = [m["content"] for m in messages if m.get("role") == "system"]
        conversa = [
            {"role": "model" if m.get("role") == "assistant" else "user", "parts": [{"text": m["content"]}]}
            for m in messages
            if m.get("role") != "system"
        ]
        payload: dict[str, Any] = {
            "contents": conversa,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": TOKENS_MAX,
                "responseMimeType": "application/json",
            },
        }
        if sistema:
            payload["systemInstruction"] = {"parts": [{"text": "\n".join(sistema)}]}
        url = f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"
        try:
            response = enviar_post(
                self._post,
                url,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=self.timeout,
                nao_repetir=cota_esgotada,
            )
            data = response.json()
        except requests.RequestException as exc:
            # A key vai na URL; redige antes de logar/lançar (nunca vaza para logs/UI).
            texto = str(exc).replace(self.api_key, "***")
            logger.warning("Falha HTTP no google modelo %s: %s: %s", self.model, type(exc).__name__, texto)
            # Causa saneada: nunca encadear a exceção crua (contém a key na URL).
            raise LLMError(
                f"Falha na chamada ao modelo {self.model}: {texto}{_aviso_de_cota(exc, self.api_key)}"
            ) from requests.HTTPError(texto)
        if "error" in data:
            raise LLMError(f"Provedor google retornou erro: {data['error']}")
        try:
            texto = data["candidates"][0]["content"]["parts"][0]["text"]
            content = json.loads(texto)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Resposta do modelo {self.model} sem candidates/texto JSON: {str(data)[:500]}") from exc
        usage = data.get("usageMetadata") or {}
        logger.info(
            "llm chamada provedor=google modelo=%s tokens_entrada=%s tokens_saida=%s",
            self.model,
            usage.get("promptTokenCount"),
            usage.get("candidatesTokenCount"),
        )
        return content
