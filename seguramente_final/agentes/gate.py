"""Gate humano: regras de pontos críticos, auditoria JSONL e nó com ``interrupt``."""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langgraph.types import interrupt

from .contrato import ContratoAgente
from .estado import novo_status
from .registro import agente

logger = logging.getLogger(__name__)

CAMPOS_CRITICOS = frozenset(
    {
        "Limite máximo de responsabilidade",
        "Limite agregado",
        "Franquia / retenção",
        "Cobertura A — indenização ao segurado",
        "Cobertura B — reembolso à sociedade",
        "Cobertura C — entidade",
    }
)

CAMPOS_MONETARIOS = frozenset(
    {
        "Limite máximo de responsabilidade",
        "Limite agregado",
        "Franquia / retenção",
    }
)

LIMITE_DIVERGENCIA_PERCENTUAL = 20.0

PADRAO_VALOR = re.compile(r"\d[\d.]*,\d+|\d[\d.]*")


def _valor_numerico(texto: Any) -> float | None:
    """Converte valores em formato pt-BR (``R$ 10.000.000,00``) em float."""
    if texto is None:
        return None
    correspondencia = PADRAO_VALOR.search(str(texto))
    if not correspondencia:
        return None
    bruto = correspondencia.group(0)
    bruto = bruto.replace(".", "").replace(",", ".") if "," in bruto else bruto.replace(".", "")
    try:
        return float(bruto)
    except ValueError:
        return None


def calcular_pontos_criticos(estado: dict[str, Any]) -> list[dict[str, Any]]:
    """Avalia o estado e devolve os pontos que exigem revisão humana.

    Regras (todas determinísticas): ambiguidade, ausência de campo crítico em
    só uma apólice, página sem texto extraído, fato presente sem evidência,
    divergência material (>20%) em campo monetário e fallback do extrator LLM.

    Args:
        estado: Estado do grafo com ``comparacao``, ``fatos``, ``documentos``
            e ``fallback_extrator``.

    Returns:
        Lista de pontos com ``codigo``, ``severidade``, ``titulo``,
        ``detalhe`` e ``campo``.
    """
    pontos: list[dict[str, Any]] = []
    comparacao = estado.get("comparacao") or []

    for row in comparacao:
        if row.get("status") == "ambigua":
            pontos.append(
                {
                    "codigo": "ambiguidade",
                    "severidade": "alta",
                    "titulo": f"{row.get('label')} — revisão humana",
                    "detalhe": f"Valor ambíguo ou conflitante em '{row.get('label')}': revisar manualmente.",
                    "campo": row.get("label"),
                }
            )

    for row in comparacao:
        if row.get("status") in {"ausente_em_a", "ausente_em_b"} and row.get("label") in CAMPOS_CRITICOS:
            pontos.append(
                {
                    "codigo": "ausente_critico",
                    "severidade": "alta",
                    "titulo": f"{row.get('label')} ausente em uma apólice",
                    "detalhe": f"Campo crítico '{row.get('label')}' localizado em só uma das apólices.",
                    "campo": row.get("label"),
                }
            )

    for indice, documento in enumerate(estado.get("documentos") or [], start=1):
        for pagina in documento.get("pages") or []:
            if pagina.get("extraction_method") in {"ocr-empty", "pdf-text-empty"}:
                pontos.append(
                    {
                        "codigo": "extracao_falhou",
                        "severidade": "media",
                        "titulo": f"Documento {indice} — página {pagina.get('page_number')} sem texto",
                        "detalhe": (
                            f"Página {pagina.get('page_number')} do documento {indice} não gerou texto "
                            f"(método {pagina.get('extraction_method')})."
                        ),
                        "campo": None,
                    }
                )

    for fato in estado.get("fatos") or []:
        if fato.get("status") == "present" and not str(fato.get("evidence") or "").strip():
            pontos.append(
                {
                    "codigo": "sem_evidencia",
                    "severidade": "media",
                    "titulo": f"{fato.get('label')} sem evidência",
                    "detalhe": f"Fato '{fato.get('label')}' marcado como presente, porém sem evidência textual.",
                    "campo": fato.get("label"),
                }
            )

    for row in comparacao:
        if row.get("status") != "diferente" or row.get("label") not in CAMPOS_MONETARIOS:
            continue
        valor_a = _valor_numerico(row.get("policy_a"))
        valor_b = _valor_numerico(row.get("policy_b"))
        if not valor_a or not valor_b:
            continue
        divergencia = abs(valor_b - valor_a) / abs(valor_a) * 100
        if divergencia > LIMITE_DIVERGENCIA_PERCENTUAL:
            pontos.append(
                {
                    "codigo": "divergencia_material",
                    "severidade": "alta",
                    "titulo": f"{row.get('label')} diverge {divergencia:.0f}%",
                    "detalhe": (
                        f"{row.get('label')}: {row.get('policy_a')} vs {row.get('policy_b')} — "
                        f"divergência de {divergencia:.0f}% acima do limite de "
                        f"{LIMITE_DIVERGENCIA_PERCENTUAL:.0f}%."
                    ),
                    "campo": row.get("label"),
                }
            )

    if estado.get("fallback_extrator"):
        pontos.append(
            {
                "codigo": "fallback_extrator",
                "severidade": "media",
                "titulo": "Extração LLM falhou; fallback offline aplicado",
                "detalhe": "O extrator por LLM não retornou fatos válidos e caiu para a extração determinística.",
                "campo": None,
            }
        )

    logger.info("Gate: %s ponto(s) crítico(s) calculado(s)", len(pontos))
    return pontos


def registrar_auditoria(
    thread_id: str,
    pontos: list[dict[str, Any]],
    decisao: dict[str, Any] | None,
    caminho: Path | str,
) -> None:
    """Grava um registro JSONL da decisão do gate (trace auditável por thread)."""
    arquivo = Path(caminho)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    registro = {
        "timestamp": datetime.now(UTC).isoformat(),
        "thread_id": thread_id,
        "actor": "humano",
        "status": "decidido" if decisao else "aguardando",
        "pontos": pontos,
        "decisao": decisao,
    }
    with arquivo.open("a", encoding="utf-8") as fluxo:
        fluxo.write(json.dumps(registro, ensure_ascii=False, default=str) + "\n")


@agente(rotulo="⚖️ Gate humano", ordem=2, grupo="maestro")
class GateHumano:
    """Nó do grafo: pausa com ``interrupt`` quando há pontos críticos."""

    contrato = ContratoAgente(
        nome="gate",
        papel="Pausa a análise para revisão humana dos pontos críticos (auditáveis em JSONL).",
        prompt_sistema=(
            "Apresente os pontos críticos ao revisor humano e aguarde a decisão "
            "(aprovar, rejeitar, comentar) antes de finalizar a análise."
        ),
        ferramentas=frozenset(),
    )

    def __init__(self, diretorio_auditoria: Path | str) -> None:
        self.diretorio_auditoria = Path(diretorio_auditoria)

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        pontos = state.get("pontos") or []
        thread_id = state.get("thread_id", "")
        codigos = Counter(str(ponto.get("codigo", "sem_codigo")) for ponto in pontos)
        logger.info("Gate thread=%s pontos=%s códigos=%s", thread_id, len(pontos), dict(sorted(codigos.items())))
        caminho = self.diretorio_auditoria / f"gate_audit_{thread_id}.jsonl"
        if not pontos or state.get("decisao_humana"):
            return {"live_status": [novo_status("gate", "humano", "sem pendências — prossegue")]}
        mensagem = f"Supervisor: {len(pontos)} ponto(s) crítico(s) exigem revisão humana antes de finalizar."
        registrar_auditoria(thread_id, pontos, None, caminho)
        decisao = interrupt({"pontos": pontos, "mensagem": mensagem})
        registrar_auditoria(thread_id, pontos, decisao, caminho)
        return {
            "decisao_humana": decisao,
            "live_status": [novo_status("gate", "humano", f"decisão: {decisao.get('acao')}")],
        }
