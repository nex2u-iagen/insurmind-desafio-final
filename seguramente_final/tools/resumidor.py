"""Síntese de resumo comparativo via LLM."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence

from ..motor_llm.base import ChatJson, LLMError
from ..prompting import bloco_memoria

logger = logging.getLogger(__name__)

PROMPT_SISTEMA = (
    "Você é um revisor de apólices D&O. Resuma as diferenças materiais entre duas apólices "
    "em no máximo 8 frases, citando campos, valores, documentos e páginas quando disponíveis. "
    "Use somente fatos e trechos fornecidos; não infira cobertura a partir de campo não localizado. "
    'Responda SOMENTE JSON no formato: {"resumo": "texto do resumo"}.'
)


class ResumidorLLM:
    """Gera o resumo final das diferenças a partir das linhas comparativas."""

    def __init__(self, cliente: ChatJson) -> None:
        self.cliente = cliente

    def summarize(
        self,
        rows: Sequence,
        memoria_contexto: list[str] | None = None,
        achados: list[dict] | None = None,
        pedido_usuario: str = "",
    ) -> str:
        """Sumariza as linhas de comparação; propaga :class:`LLMError` em falha.

        Args:
            rows: Linhas comparadas (dict ou modelo).
            memoria_contexto: Lembranças de análises anteriores (bloco no prompt).
            achados: Vereditos dos especialistas e trechos documentais recuperados.
            pedido_usuario: Solicitação que orientou o plano de análise.

        Returns:
            Resumo em no máximo 8 frases (string crua é aceita como resumo).

        Raises:
            LLMError: Resposta vazia ou de tipo inesperado.
        """
        linhas = [r.to_dict() if hasattr(r, "to_dict") else dict(r) for r in rows]
        partes: list[str] = []
        bloco = bloco_memoria(memoria_contexto)
        if bloco:
            partes.append(bloco)
        if pedido_usuario.strip():
            partes.append(f"Pedido do usuário: {pedido_usuario.strip()}")
        contexto_especialistas = []
        for achado in achados or []:
            contexto_especialistas.append(
                {
                    "especialista": achado.get("especialista"),
                    "veredito": str(achado.get("veredito", ""))[:500],
                    "veredito_llm": str(achado.get("veredito_llm", ""))[:800],
                    "trechos_documentais": [
                        {
                            **{chave: trecho.get(chave) for chave in ("document_id", "document_name", "page_number")},
                            "text": str(trecho.get("text", ""))[:1200],
                        }
                        for trecho in (achado.get("trechos_documentais") or [])[:2]
                    ],
                }
            )
        if contexto_especialistas:
            partes.append(
                "Achados dos especialistas e evidências recuperadas:\n"
                + json.dumps(contexto_especialistas, ensure_ascii=False, default=str)
            )
        partes.append(json.dumps(linhas, ensure_ascii=False, default=str))
        dados = self.cliente.chat_json(
            [
                {"role": "system", "content": PROMPT_SISTEMA},
                {"role": "user", "content": "\n".join(partes)},
            ],
            temperature=0.2,
        )
        if isinstance(dados, str):
            resumo = dados.strip()
        elif isinstance(dados, dict):
            resumo = str(dados.get("resumo", "")).strip()
        else:
            raise LLMError("Resumo do modelo vazio.")
        if not resumo:
            raise LLMError("Resumo do modelo vazio.")
        return resumo
