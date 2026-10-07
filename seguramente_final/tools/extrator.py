"""Extração de fatos de apólices via LLM, com fallback determinístico offline."""

from __future__ import annotations

import json
import logging

from ..models import PolicyDocument, PolicyFact
from ..motor_llm.base import ChatJson, LLMError
from ..rules import RuleBasedExtractor, normalizar_valor
from ..schema import FIELD_DEFINITIONS

logger = logging.getLogger(__name__)

PROMPT_SISTEMA = (
    "Você é um especialista em apólices de seguros D&O. Extraia TODOS os fatos do documento "
    "apresentado no formato JSON exigido. Seja fiel ao texto; nunca invente valores."
)

ROTULOS_SCHEMA = "; ".join(f"{campo['label']} ({campo['category']})" for campo in FIELD_DEFINITIONS)

PROMPT_USUARIO = (
    "Documento da apólice:\n{document}\n\n"
    f'Use SOMENTE estes valores em "label" (categoria entre parênteses): {ROTULOS_SCHEMA}\n\n'
    "Responda SOMENTE com JSON no formato:\n"
    '{"facts": [{"label": "...", "category": "...", "value": "...", "evidence": "...", "page": 1}]}'
)


class ExtratorLLM:
    """Estratégia de extração com modelo de linguagem (cliente injetado)."""

    name = "llm"

    def __init__(self, cliente: ChatJson, model: str | None = None) -> None:
        self.cliente = cliente
        self.model = model or getattr(cliente, "model", "")
        self.fallback_aplicado = False
        self.motivo_fallback = ""
        self.fatos_llm = 0
        self.complemento_regras = 0
        self.conflitos = 0
        self.ultimo_fallback = False
        self.ultimo_motivo_fallback = ""

    def extract(self, document) -> list:
        """Extrai fatos do documento; fallback offline em caso de falha do modelo.

        Aceita ``PolicyDocument`` ou dict serializado (o mesmo contrato das
        demais tools), normalizando antes de montar o prompt.
        """
        alvo = self._como_documento(document)
        self.fatos_llm = 0
        self.complemento_regras = 0
        self.conflitos = 0
        self.ultimo_fallback = False
        self.ultimo_motivo_fallback = ""
        texto = self._texto_do_documento(alvo)[:12000]
        # replace (não .format): o prompt tem JSON literal com chaves {...}.
        messages = [
            {"role": "system", "content": PROMPT_SISTEMA},
            {"role": "user", "content": PROMPT_USUARIO.replace("{document}", texto)},
        ]
        try:
            dados = self.cliente.chat_json(messages, temperature=0.1)
            fatos_llm = self._coerce_facts(dados, alvo)
            if not fatos_llm:
                raise LLMError("LLM retornou lista de fatos vazia.")
            fatos_regras = RuleBasedExtractor().extract(alvo)
            fatos, complemento, conflitos = self._mesclar_fatos(fatos_llm, fatos_regras, alvo)
            self.fatos_llm = len(fatos_llm)
            self.complemento_regras = complemento
            self.conflitos = conflitos
            logger.info(
                "Extração concluída documento=%s provider=llm campos=%s/%s complemento_regras=%s conflitos=%s",
                alvo.document_id,
                self.fatos_llm,
                len(FIELD_DEFINITIONS),
                complemento,
                conflitos,
            )
            if complemento or conflitos:
                logger.warning(
                    "Cobertura LLM incompleta documento=%s campos_llm=%s/%s complementados=%s ambiguos=%s",
                    alvo.document_id,
                    self.fatos_llm,
                    len(FIELD_DEFINITIONS),
                    complemento,
                    conflitos,
                )
            return fatos
        except (LLMError, ValueError) as exc:
            logger.warning(
                "Extração por LLM falhou documento=%s (%s); usando extração offline.",
                alvo.document_id,
                exc,
            )
            self.fallback_aplicado = True
            self.motivo_fallback = str(exc)
            self.ultimo_fallback = True
            self.ultimo_motivo_fallback = str(exc)
            fatos = RuleBasedExtractor().extract(alvo)
            self.complemento_regras = len(fatos)
            logger.info(
                "Extração concluída documento=%s provider=rules fallback=1 campos=%s/%s",
                alvo.document_id,
                len(fatos),
                len(FIELD_DEFINITIONS),
            )
            return fatos

    @staticmethod
    def _como_documento(document) -> PolicyDocument:
        """Normaliza a entrada em ``PolicyDocument`` (aceita dict serializado)."""
        if isinstance(document, dict):
            from ..models import PolicyDocument

            return PolicyDocument.from_dict(document)
        return document

    @staticmethod
    def _texto_do_documento(document) -> str:
        """Texto das páginas (sem o repr do objeto) quando o alvo tem ``pages``."""
        paginas = getattr(document, "pages", None)
        if not paginas:
            return str(document)
        texto = "\n".join(str(pagina.text or "") for pagina in paginas).strip()
        return texto or str(document)

    @staticmethod
    def _coerce_facts(dados: dict, document: PolicyDocument) -> list[PolicyFact]:
        """Normaliza a resposta do modelo em ``PolicyFact`` do schema canônico.

        Aceita as chaves ``facts`` (prompt real) e ``fatos`` (variante em
        português que alguns modelos devolvem), além de ``label``/``name``.
        """
        bruto = dados.get("facts") if isinstance(dados, dict) else None
        if bruto is None and isinstance(dados, dict):
            bruto = dados.get("fatos")
        if isinstance(bruto, str):
            bruto = json.loads(bruto)
        if not isinstance(bruto, list):
            return []
        categorias = {campo["label"]: campo["category"] for campo in FIELD_DEFINITIONS}
        fatos = []
        for item in bruto:
            if not isinstance(item, dict):
                continue
            rotulo = str(item.get("label") or item.get("name") or "").strip()
            if not rotulo:
                continue
            if rotulo not in categorias:
                logger.warning("LLM retornou rótulo fora do schema documento=%s label=%r", document.document_id, rotulo)
                continue
            valor = str(item.get("value") or "").strip() or None
            pagina = item.get("page") if isinstance(item.get("page"), int) else None
            fatos.append(
                PolicyFact(
                    document_id=document.document_id,
                    category=categorias[rotulo],
                    label=rotulo,
                    value=valor,
                    status="present" if valor else "not_found",
                    confidence=0.9 if valor else 0.5,
                    page=pagina,
                    evidence=str(item.get("evidence") or "").strip() or "Extraído por LLM.",
                    normalized_value=normalizar_valor(valor),
                    source=getattr(document, "source", None),
                )
            )
        return [f for f in fatos if f.label]

    @staticmethod
    def _mesclar_fatos(
        fatos_llm: list[PolicyFact],
        fatos_regras: list[PolicyFact],
        document: PolicyDocument,
    ) -> tuple[list[PolicyFact], int, int]:
        """Completa omissões do LLM com regras e sinaliza divergências como ambíguas."""
        llm_por_rotulo = {fato.label: fato for fato in fatos_llm}
        regras_por_rotulo = {fato.label: fato for fato in fatos_regras}
        fatos: list[PolicyFact] = []
        complemento = 0
        conflitos = 0

        for campo in FIELD_DEFINITIONS:
            rotulo = campo["label"]
            fato_llm = llm_por_rotulo.get(rotulo)
            fato_regra = regras_por_rotulo.get(rotulo)
            if fato_regra is None:
                fato_regra = PolicyFact(
                    document_id=document.document_id,
                    category=campo["category"],
                    label=rotulo,
                    value=None,
                    status="not_found",
                    confidence=0.0,
                    page=None,
                    evidence="Campo ausente na saída dos extratores.",
                    source=document.source,
                )

            if fato_llm is None or fato_llm.status == "not_found":
                fatos.append(fato_regra)
                complemento += 1
                continue

            if fato_llm.status == "ambiguous":
                fatos.append(fato_llm)
                continue

            if fato_llm.status == "present" and fato_regra.status == "present":
                valor_llm = fato_llm.normalized_value or normalizar_valor(fato_llm.value) or ""
                valor_regra = fato_regra.normalized_value or normalizar_valor(fato_regra.value) or ""
                equivalentes = valor_llm == valor_regra or valor_llm in valor_regra or valor_regra in valor_llm
                if not equivalentes:
                    fatos.append(
                        PolicyFact(
                            document_id=document.document_id,
                            category=campo["category"],
                            label=rotulo,
                            value=f"LLM: {fato_llm.value} | regra: {fato_regra.value}",
                            status="ambiguous",
                            confidence=min(fato_llm.confidence, fato_regra.confidence),
                            page=fato_llm.page or fato_regra.page,
                            evidence=(
                                f"Divergência entre extração LLM ({fato_llm.evidence}, p. {fato_llm.page or '-'}); "
                                f"e regra ({fato_regra.evidence}, p. {fato_regra.page or '-'})."
                            ),
                            source=document.source,
                        )
                    )
                    conflitos += 1
                    continue

                if fato_llm.evidence == "Extraído por LLM." and fato_regra.evidence:
                    fatos.append(fato_regra)
                    complemento += 1
                    continue
                if fato_llm.page is None and fato_regra.page is not None:
                    fato_llm.page = fato_regra.page
                if fato_llm.evidence == "Extraído por LLM.":
                    fato_llm.evidence = fato_regra.evidence

            fatos.append(fato_llm)

        return fatos, complemento, conflitos
