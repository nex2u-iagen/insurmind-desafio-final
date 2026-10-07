"""Nós do fluxo: ingerir, extrair, comparar, revisar, sintetizar e persistir."""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path
from typing import Any

from ..compare import resumir_diferencas
from ..ingest import exigir_documentos_distintos
from ..models import PolicyDocument
from ..motor_llm import LLMError
from ..storage import PolicyStore
from ..tools import executar_ferramenta
from .contrato import ContratoAgente
from .estado import novo_status, reidratar_documento, reidratar_linha
from .gate import calcular_pontos_criticos
from .memoria import Memoria
from .registro import agente

logger = logging.getLogger(__name__)


@agente(rotulo="Ingestor", ordem=10)
class IngestorNode:
    """Ingesta dos PDFs em dicts JSON-safe no estado."""

    contrato = ContratoAgente(
        nome="ingestar",
        papel="Ingesta as apólices em dicts JSON-safe com páginas e método de extração.",
        prompt_sistema=(
            "Materialize as apólices informadas em documentos JSON-safe, acionando OCR quando uma "
            "página não tiver camada textual. Não interprete o conteúdo das apólices."
        ),
        ferramentas=frozenset({"ingestar_documentos", "extrair_texto_ocr"}),
    )

    def __init__(self, memoria: Any = None) -> None:
        self.memoria = memoria

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        documentos = executar_ferramenta(
            self.contrato,
            "ingestar_documentos",
            state["caminhos"],
            state.get("nomes"),
            forcar_ocr=bool(state.get("simular_ocr", False)),
        )
        # Falha cedo (antes de gastar LLM) quando o mesmo arquivo entrou nas duas posições.
        exigir_documentos_distintos([str(d.get("document_id", "")) for d in documentos if isinstance(d, dict)])
        for documento in documentos:
            paginas = documento.get("pages") or []
            metodos = Counter(str(pagina.get("extraction_method") or "unknown") for pagina in paginas)
            logger.info(
                "Documento ingerido id=%s nome=%s paginas=%s caracteres=%s metodos=%s",
                documento.get("document_id", "?"),
                documento.get("name", "?"),
                len(paginas),
                sum(len(str(pagina.get("text") or "")) for pagina in paginas),
                dict(sorted(metodos.items())),
            )
        indexacao = {"available": False, "indexed_pages": 0, "skipped_pages": 0}
        indexar = getattr(self.memoria, "indexar_documentos", None)
        if callable(indexar):
            try:
                indexacao = indexar(documentos)
            except Exception as exc:  # noqa: BLE001 — a análise determinística segue disponível.
                logger.warning("Indexação documental no epochDB falhou (%s: %s).", type(exc).__name__, exc)
        logger.info(
            "Indexação documental epochDB disponível=%s paginas_novas=%s paginas_inalteradas=%s documentos=%s",
            bool(indexacao.get("available")),
            indexacao.get("indexed_pages", 0),
            indexacao.get("skipped_pages", 0),
            len(documentos),
        )
        return {
            "documentos": documentos,
            "indexacao_documental": indexacao,
            "live_status": [
                novo_status(
                    "ingestar",
                    "ingestor",
                    f"{len(documentos)} documento(s); epochDB: "
                    f"{indexacao.get('indexed_pages', 0)} página(s) indexada(s)"
                    if indexacao.get("available")
                    else f"{len(documentos)} documento(s); epochDB indisponível",
                )
            ],
        }


@agente(rotulo="Extrator", ordem=20)
class ExtratorNode:
    """Executa a estratégia de extração (LLM ou regras) sobre cada documento."""

    contrato = ContratoAgente(
        nome="extrair",
        papel="Extrai os 19 fatos normalizados de cada apólice (LLM ou regras).",
        prompt_sistema=(
            "Extraia os 19 fatos normalizados do schema D&O de cada apólice com status, evidência "
            'textual e página. Em modo LLM, responda SOMENTE JSON válido: {"facts": [...]}.'
        ),
        ferramentas=frozenset({"extrair_texto_ocr"}),
    )

    def __init__(self, extrator: Any) -> None:
        self.extrator = extrator

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        documentos = [reidratar_documento(d) for d in state.get("documentos") or []]
        fatos: list[dict[str, Any]] = []
        estatisticas: list[dict[str, Any]] = []
        for documento in documentos:
            documento.facts = self.extrator.extract(documento)
            fatos.extend(fato.to_dict() for fato in documento.facts)
            estados = Counter(fato.status for fato in documento.facts)
            estatistica = {
                "document_id": documento.document_id,
                "provider": self.extrator.name,
                "campos": len(documento.facts),
                "status": dict(sorted(estados.items())),
                "campos_llm": int(getattr(self.extrator, "fatos_llm", 0)),
                "complemento_regras": int(getattr(self.extrator, "complemento_regras", 0)),
                "conflitos": int(getattr(self.extrator, "conflitos", 0)),
                "fallback": bool(getattr(self.extrator, "ultimo_fallback", False)),
            }
            estatisticas.append(estatistica)
            logger.info(
                "Extração documento=%s provider=%s campos=%s/19 status=%s llm=%s complemento_regras=%s "
                "conflitos=%s fallback=%s",
                documento.document_id,
                self.extrator.name,
                estatistica["campos"],
                estatistica["status"],
                estatistica["campos_llm"],
                estatistica["complemento_regras"],
                estatistica["conflitos"],
                estatistica["fallback"],
            )
            if estatistica["fallback"]:
                logger.warning(
                    "Fallback de extração aplicado documento=%s motivo=%s",
                    documento.document_id,
                    getattr(self.extrator, "ultimo_motivo_fallback", "indisponível"),
                )
        fallback = bool(getattr(self.extrator, "fallback_aplicado", False))
        return {
            "documentos": [documento.to_dict() for documento in documentos],
            "fatos": fatos,
            "estatisticas_extracao": estatisticas,
            "fallback_extrator": fallback,
            "motivo_degradacao": str(getattr(self.extrator, "motivo_fallback", "")) if fallback else "",
            "live_status": [novo_status("extrair", "extrator", f"{len(fatos)} fatos ({self.extrator.name})")],
        }


@agente(rotulo="Comparador", ordem=90)
class ComparadorNode:
    """Compara as duas apólices (19 linhas com evidência e página)."""

    contrato = ContratoAgente(
        nome="comparar",
        papel="Compara as duas apólices linha a linha (19 campos com evidência e página).",
        prompt_sistema=(
            "Compare os 19 campos do schema D&O entre as duas apólices, sempre citando a evidência "
            "textual e a página de origem de cada lado."
        ),
        ferramentas=frozenset({"comparar_apolices"}),
    )

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        documentos = state.get("documentos") or []
        linhas = executar_ferramenta(self.contrato, "comparar_apolices", documentos[0], documentos[1])
        status = Counter(str(linha.get("status", "sem_status")) for linha in linhas)
        logger.info("Comparação concluída linhas=%s status=%s", len(linhas), dict(sorted(status.items())))
        return {
            "comparacao": linhas,
            "live_status": [novo_status("comparar", "comparador", f"{len(linhas)} linha(s)")],
        }


@agente(rotulo="Revisor", ordem=100)
class RevisorNode:
    """Aplica as regras de pontos críticos (pré-gate humano)."""

    contrato = ContratoAgente(
        nome="revisor",
        papel="Aplica as regras determinísticas de pontos críticos antes do gate humano.",
        prompt_sistema=(
            "Avalie ambiguidades, campos críticos ausentes, páginas sem texto, evidências faltantes "
            "e divergências materiais; devolva somente os pontos que exigem revisão humana."
        ),
        ferramentas=frozenset(),
    )

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        pontos = calcular_pontos_criticos(state)
        codigos = Counter(str(ponto.get("codigo", "sem_codigo")) for ponto in pontos)
        logger.info("Revisão concluída pontos=%s códigos=%s", len(pontos), dict(sorted(codigos.items())))
        return {
            "pontos": pontos,
            "live_status": [novo_status("revisor", "revisor", f"{len(pontos)} ponto(s) crítico(s)")],
        }


@agente(rotulo="Sintetizador", ordem=110)
class SintetizadorNode:
    """Gera o resumo executivo (offline ou via cliente LLM) após o gate."""

    contrato = ContratoAgente(
        nome="sintetizar",
        papel="Gera o resumo executivo das diferenças após a decisão humana.",
        prompt_sistema=(
            "Redija um resumo executivo das diferenças e lacunas em linguagem objetiva; nunca emita "
            "parecer jurídico. Cai para o resumo offline quando o LLM falhar."
        ),
        ferramentas=frozenset({"resumir_comparacao"}),
    )

    def __init__(self, cliente: Any = None) -> None:
        self.cliente = cliente
        self.motivo_fallback = ""

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        linhas = [reidratar_linha(linha) for linha in state.get("comparacao") or []]
        resumo, fallback = self._resumir(
            linhas,
            state.get("memoria_contexto"),
            state.get("achados") or [],
            str(state.get("pedido_usuario") or ""),
        )
        decisao = state.get("decisao_humana")
        logger.info(
            "Síntese concluída provider=%s fallback=%s caracteres=%s evidencias_especialistas=%s",
            "offline" if fallback or self.cliente is None else "llm",
            fallback,
            len(resumo),
            sum(len(achado.get("trechos_documentais") or []) for achado in state.get("achados") or []),
        )
        if decisao:
            resumo = f"{resumo} Análise revisada por humano: {decisao.get('acao')}."
        saida: dict[str, Any] = {
            "resumo": resumo,
            "fallback_resumo": fallback,
            "live_status": [novo_status("sintetizar", "sintetizador")],
        }
        if fallback and not state.get("motivo_degradacao"):
            saida["motivo_degradacao"] = self.motivo_fallback
        return saida

    def _resumir(
        self,
        linhas: list,
        memoria_contexto: list[str] | None = None,
        achados: list[dict[str, Any]] | None = None,
        pedido_usuario: str = "",
    ) -> tuple[str, bool]:
        """Resumo via tool; devolve ``(texto, fallback_offline)``."""
        try:
            texto = executar_ferramenta(
                self.contrato,
                "resumir_comparacao",
                linhas,
                self.cliente,
                list(memoria_contexto or []),
                achados=list(achados or []),
                pedido_usuario=pedido_usuario,
            )
            return texto, False
        except LLMError as exc:
            logger.warning("Resumo por LLM falhou (%s); usando resumo offline.", exc)
            self.motivo_fallback = str(exc)
            return resumir_diferencas(linhas), True


@agente(rotulo="Persistidor", ordem=120)
class PersistidorNode:
    """Persiste documentos/comparação no SQLite e registra a memória de longo prazo."""

    contrato = ContratoAgente(
        nome="persistir",
        papel="Persiste documentos/comparação no SQLite e registra a memória de longo prazo.",
        prompt_sistema=(
            "Grave documentos, comparação e memória da análise concluída; falhas de memória nunca "
            "derrubam uma análise já finalizada."
        ),
        ferramentas=frozenset(),
    )

    def __init__(self, store_path: str | Path, memoria: Memoria | None = None) -> None:
        self.store_path = Path(store_path)
        self.memoria = memoria

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        documentos = [reidratar_documento(d) for d in state.get("documentos") or []]
        linhas = [reidratar_linha(linha) for linha in state.get("comparacao") or []]
        if len(documentos) == 2 and linhas:
            store = PolicyStore(self.store_path)
            for documento in documentos:
                store.save_document(documento)
            store.save_comparison(documentos[0], documentos[1], linhas)
            logger.info(
                "Persistência SQLite concluída documentos=%s páginas=%s fatos=%s comparações=%s arquivo=%s",
                len(documentos),
                sum(len(documento.pages) for documento in documentos),
                sum(len(documento.facts) for documento in documentos),
                len(linhas),
                self.store_path,
            )
        if self.memoria is not None:
            self._lembrar(state, documentos, linhas)
        return {"live_status": [novo_status("persistir", "persistidor", str(self.store_path))]}

    def _lembrar(self, state: dict[str, Any], documentos: list[PolicyDocument], linhas: list) -> None:
        """Registra a análise na memória (JSONL local e epochdb quando disponível)."""
        nomes = " vs ".join(d.name for d in documentos) if documentos else "apólices"
        thread_id = str(state.get("thread_id", ""))
        assuntos = sorted(
            {linha.category for linha in linhas if linha.category and linha.status not in {"igual", "ambos_ausentes"}}
        )
        parte_assuntos = f" — assuntos: {', '.join(assuntos)}" if assuntos else ""
        texto = (
            f"Análise {thread_id}: {nomes} — {len(linhas)} campo(s), resumo: {state.get('resumo', '')}{parte_assuntos}"
        )
        triples: list[tuple] = [("analise", "thread", thread_id)]
        triples.extend(("analise", "documento", documento.document_id) for documento in documentos)
        triples.extend((thread_id, "aborda", assunto) for assunto in assuntos)
        if len(documentos) == 2:
            triples.append((documentos[0].document_id, "compara_com", documentos[1].document_id))
        try:
            self.memoria.remember(
                texto,
                metadata={
                    "thread_id": thread_id,
                    "provedor": state.get("provedor", ""),
                    "documentos": [d.document_id for d in documentos],
                    "decisao": state.get("decisao_humana"),
                    "assuntos": assuntos,
                },
                triples=triples,
            )
            finalizar = getattr(self.memoria, "finalizar", None)
            if callable(finalizar):
                finalizar()
            logger.info(
                "Memória da análise persistida thread=%s documentos=%s assuntos=%s",
                thread_id,
                len(documentos),
                len(assuntos),
            )
        except Exception as exc:  # noqa: BLE001 — memória nunca derruba a análise concluída.
            logger.warning(
                "Falha ao registrar memória (%s: %s); seguindo sem persistência de memória.", type(exc).__name__, exc
            )
