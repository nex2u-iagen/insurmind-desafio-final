"""Base dos especialistas — contrato comum de fatia, veredito e achado."""

from __future__ import annotations

import json
import logging
from abc import ABC
from typing import Any

from ...motor_llm.base import ChatJson
from ...prompting import bloco_memoria
from ..contrato import ContratoAgente
from ..estado import novo_status

logger = logging.getLogger(__name__)


class EspecialistaNode(ABC):
    """Base dos especialistas: fatia do schema, veredito e achado no blackboard.

    Cada subclasse declara ``nome``, ``categorias``, ``foco`` e
    ``prompt_sistema``; comportamentos específicos da área crescem isolados na
    própria classe (hook :meth:`veredito_dominio`).
    """

    nome: str
    categorias: frozenset[str]
    foco: str
    prompt_sistema: str

    def __init__(self, cliente: ChatJson | None = None, memoria: Any = None) -> None:
        for atributo in ("nome", "categorias", "foco", "prompt_sistema"):
            if not getattr(self, atributo, None):
                raise ValueError(f"Especialista {type(self).__name__} deve declarar '{atributo}'.")
        self.cliente = cliente
        self.memoria = memoria

    @property
    def contrato(self) -> ContratoAgente:
        """Contrato declarativo do especialista (etapa ``especialista_<nome>``)."""
        return ContratoAgente(
            nome=f"especialista_{self.nome}",
            papel=f"Especialista em {self.foco}",
            prompt_sistema=self.prompt_sistema,
            ferramentas=frozenset(),
        )

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """Analisa a fatia atribuída e devolve achado + entrada de trace."""
        fatos = [f for f in state.get("fatos") or [] if f.get("category") in self.categorias]
        instrucao = (state.get("instrucoes") or {}).get(self.nome) or state.get("pedido_usuario") or ""
        trechos = self._recuperar_trechos(state, instrucao, fatos)
        por_documento: dict[str, int] = {}
        paginas_por_documento: dict[str, list[int]] = {}
        for trecho in trechos:
            document_id = str(trecho.get("document_id", "?"))
            por_documento[document_id] = por_documento.get(document_id, 0) + 1
            paginas_por_documento.setdefault(document_id, []).append(int(trecho.get("page_number") or 0))
        logger.info(
            "Contexto especialista=%s fatos=%s trechos_por_documento=%s paginas=%s",
            self.nome,
            len(fatos),
            por_documento,
            paginas_por_documento,
        )
        veredito = self.veredito_dominio(fatos)
        achado: dict[str, Any] = {
            "especialista": self.nome,
            "categorias": sorted(self.categorias),
            "veredito": veredito,
            "instrucao": instrucao,
            "ferramentas": sorted(self.contrato.ferramentas),
            "trechos_documentais": trechos,
        }
        if self.cliente is not None:
            achado["veredito_llm"] = self._veredito_llm(
                fatos, instrucao, state.get("memoria_contexto"), trechos
            )
            logger.info(
                "Veredito especialista=%s provider=llm resultado=%s",
                self.nome,
                "recebido" if achado["veredito_llm"] else "regras_mantidas",
            )
        else:
            logger.info("Veredito especialista=%s provider=regras", self.nome)
        return {
            "achados": [achado],
            "live_status": [novo_status(f"especialista_{self.nome}", self.nome, veredito)],
        }

    def _recuperar_trechos(
        self,
        state: dict[str, Any],
        instrucao: str,
        fatos: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Recupera páginas do epochDB e completa fontes sem hit com evidências estruturadas."""
        documentos = state.get("documentos") or []
        document_ids = [str(documento.get("document_id", "")) for documento in documentos]
        recuperador = getattr(self.memoria, "recuperar_trechos", None)
        recuperados: list[dict[str, Any]] = []
        if callable(recuperador) and document_ids:
            pergunta = f"{self.foco}. {instrucao or state.get('pedido_usuario', '')}"
            try:
                recuperados = recuperador(pergunta, document_ids, k=2)
            except Exception as exc:  # noqa: BLE001 — fatos estruturados continuam sendo fallback.
                logger.warning("Recuperação epochDB para %s falhou (%s: %s).", self.nome, type(exc).__name__, exc)

        trechos: list[dict[str, Any]] = []
        for documento in documentos:
            document_id = str(documento.get("document_id", ""))
            do_documento = [trecho for trecho in recuperados if trecho.get("document_id") == document_id]
            if do_documento:
                trechos.extend(do_documento[:2])
                continue
            evidencias = [
                fato
                for fato in fatos
                if str(fato.get("document_id", "")) == document_id
                and fato.get("status") == "present"
                and str(fato.get("evidence") or "").strip()
                and fato.get("evidence") != "Extraído por LLM."
            ]
            trechos.extend(
                {
                    "document_id": document_id,
                    "document_name": str(documento.get("name") or document_id),
                    "page_number": fato.get("page"),
                    "extraction_method": "fato_estruturado",
                    "text": str(fato.get("evidence"))[:1200],
                }
                for fato in evidencias[:2]
            )
        return trechos

    def veredito_dominio(self, fatos: list[dict[str, Any]]) -> str:
        """Veredito determinístico da fatia; cada especialista pode sobrescrever."""
        presentes = [f for f in fatos if f.get("status") == "present"]
        lacunas = [f.get("label") for f in fatos if f.get("status") == "not_found"]
        veredito = f"{self.nome}: {len(presentes)}/{len(fatos)} campos presentes"
        return veredito + (f"; lacunas: {', '.join(map(str, lacunas))}" if lacunas else "; sem lacunas.")

    def _veredito_llm(
        self,
        fatos: list[dict[str, Any]],
        instrucao: str = "",
        memoria_contexto: list[str] | None = None,
        trechos_documentais: list[dict[str, Any]] | None = None,
    ) -> str:
        """Pedindo ao modelo um veredito qualitativo sobre a fatia (melhor esforço)."""
        try:
            partes: list[str] = []
            bloco = bloco_memoria(memoria_contexto)
            if bloco:
                partes.append(bloco)
            if instrucao:
                partes.append(f"Instrução do supervisor: {instrucao}")
            partes.append(json.dumps(fatos, ensure_ascii=False, default=str))
            if trechos_documentais:
                partes.append(
                    "Trechos documentais recuperados; baseie afirmações sobre as apólices somente neles "
                    "e cite nome do documento e página. Se forem insuficientes, declare a lacuna:\n"
                    + json.dumps(trechos_documentais, ensure_ascii=False, default=str)
                )
            resposta = self.cliente.chat_json(
                [
                    {"role": "system", "content": self.prompt_sistema},
                    {"role": "user", "content": "\n".join(partes)},
                ]
            )
            return str(resposta.get("veredito", "")).strip()
        except Exception as exc:  # noqa: BLE001 — veredito LLM é opcional; regras já cobrem o achado.
            logger.warning(
                "Veredito LLM falhou especialista=%s erro=%s; mantendo veredito de regras.",
                self.nome,
                exc,
            )
            return ""
