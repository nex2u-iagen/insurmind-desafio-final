"""Telemetria do fluxo de agentes — bus de eventos por thread para o front.

Módulo de observabilidade compartilhado por ``tools`` e ``agentes`` (na raiz
para não criar dependência entre as camadas). Os eventos são publicados por
``thread_id`` via :class:`contextvars.ContextVar`, setado pelo orquestrador em
torno do ``invoke`` do grafo. Consumidores (painel da orquestra) leem
:func:`eventos_da_thread`; resultados em background ficam em
:func:`guardar_resultado`.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import Counter
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, TypeVar

from langgraph.errors import GraphInterrupt

logger = logging.getLogger(__name__)

T = TypeVar("T")

_thread_id: ContextVar[str | None] = ContextVar("telemetria_thread", default=None)
_origem: ContextVar[str | None] = ContextVar("telemetria_origem", default=None)
_lock = threading.Lock()
_eventos: dict[str, list[dict[str, Any]]] = {}
_resultados: dict[str, tuple[str, Any]] = {}


def _resumo_saida(parcial: dict[str, Any]) -> str:
    """Resume métricas da saída do nó sem registrar texto documental ou prompts."""
    metricas: list[str] = []
    documentos = parcial.get("documentos")
    if isinstance(documentos, list):
        paginas = [
            pagina
            for documento in documentos
            if isinstance(documento, dict)
            for pagina in documento.get("pages", [])
        ]
        metodos = Counter(str(pagina.get("extraction_method") or "unknown") for pagina in paginas)
        metricas.append(f"documentos={len(documentos)} paginas={len(paginas)}")
        if metodos:
            resumo_metodos = ",".join(
                f"{metodo}:{quantidade}" for metodo, quantidade in sorted(metodos.items())
            )
            metricas.append("metodos=" + resumo_metodos)

    for chave, rotulo in (("fatos", "fatos"), ("comparacao", "comparacao")):
        itens = parcial.get(chave)
        if isinstance(itens, list):
            estados = Counter(str(item.get("status") or "sem_status") for item in itens if isinstance(item, dict))
            detalhes = ",".join(f"{status}:{quantidade}" for status, quantidade in sorted(estados.items()))
            metricas.append(f"{rotulo}={len(itens)}" + (f"[{detalhes}]" if detalhes else ""))

    estatisticas = parcial.get("estatisticas_extracao")
    if isinstance(estatisticas, list):
        metricas.append(
            "extracao="
            + ";".join(
                f"{item.get('document_id', '?')}:{item.get('campos', 0)}/19"
                f"(llm={item.get('campos_llm', 0)},regras={item.get('complemento_regras', 0)},"
                f"conflitos={item.get('conflitos', 0)})"
                for item in estatisticas
                if isinstance(item, dict)
            )
        )

    pontos = parcial.get("pontos")
    if isinstance(pontos, list):
        codigos = Counter(str(ponto.get("codigo") or "sem_codigo") for ponto in pontos if isinstance(ponto, dict))
        detalhes = ",".join(f"{codigo}:{quantidade}" for codigo, quantidade in sorted(codigos.items()))
        metricas.append(f"pontos={len(pontos)}" + (f"[{detalhes}]" if detalhes else ""))

    achados = parcial.get("achados")
    if isinstance(achados, list):
        especialistas = [str(achado.get("especialista", "?")) for achado in achados if isinstance(achado, dict)]
        trechos = sum(
            len(achado.get("trechos_documentais") or []) for achado in achados if isinstance(achado, dict)
        )
        metricas.append(f"especialistas={','.join(especialistas)} trechos_recuperados={trechos}")

    indexacao = parcial.get("indexacao_documental")
    if isinstance(indexacao, dict):
        metricas.append(
            "epochdb="
            f"{'disponivel' if indexacao.get('available') else 'indisponivel'}"
            f" indexadas={indexacao.get('indexed_pages', 0)} puladas={indexacao.get('skipped_pages', 0)}"
        )

    for chave in ("fallback_extrator", "fallback_resumo"):
        if chave in parcial:
            metricas.append(f"{chave}={int(bool(parcial[chave]))}")
    if isinstance(parcial.get("resumo"), str):
        metricas.append(f"resumo_chars={len(parcial['resumo'])}")
    if isinstance(parcial.get("decisao_humana"), dict):
        metricas.append(f"decisao={parcial['decisao_humana'].get('acao', 'registrada')}")
    return " ".join(metricas) or "sem métricas de saída"


def rodar_com_contexto(thread_id: str, funcao: Callable[[], T]) -> T:
    """Executa ``funcao`` com a thread de análise corrente para publicação."""
    token = _thread_id.set(thread_id)
    try:
        return funcao()
    finally:
        _thread_id.reset(token)


@contextmanager
def origem_agente(nome: str | None):
    """Marca o agente acionador no contexto (eventos publicados carregam a origem)."""
    token = _origem.set(nome)
    try:
        yield
    finally:
        _origem.reset(token)


def publicar(etapa: str, status: str, detalhe: str = "") -> None:
    """Publica um evento da etapa atual (no-op sem contexto de thread)."""
    thread_id = _thread_id.get()
    if not thread_id:
        return
    evento = {
        "thread_id": thread_id,
        "etapa": etapa,
        "status": status,
        "detalhe": detalhe,
        "origem": _origem.get() or "",
    }
    with _lock:
        _eventos.setdefault(thread_id, []).append(evento)


def eventos_da_thread(thread_id: str | None) -> list[dict[str, Any]]:
    """Cópia dos eventos publicados para a thread (ordem de execução)."""
    if not thread_id:
        return []
    with _lock:
        return list(_eventos.get(thread_id, []))


def limpar_eventos(thread_id: str) -> None:
    """Descarta eventos/resultados anteriores da thread."""
    with _lock:
        _eventos.pop(thread_id, None)
        _resultados.pop(thread_id, None)


def guardar_resultado(thread_id: str, chave: str, valor: Any) -> None:
    """Publica o desfecho da execução em background (``fim``, ``gate``, ``erro``)."""
    with _lock:
        _resultados[thread_id] = (chave, valor)
    publicar("resultado", chave)


def resultado_da_thread(thread_id: str | None) -> tuple[str, Any] | None:
    """Desfecho publicado pela worker (``None`` enquanto executa)."""
    if not thread_id:
        return None
    with _lock:
        return _resultados.get(thread_id)


def com_evento(etapa: str, no: Callable[[dict], dict], origem: str = "") -> Callable[[dict], dict]:
    """Envolve um nó do grafo publicando início/fim (``pausa`` no interrupt).

    Args:
        etapa: Id da etapa no grafo.
        no: Nó original do grafo.
        origem: Agente dono da execução (padrão: a própria ``etapa``).
    """

    def invocar(state: dict[str, Any]) -> dict[str, Any]:
        with origem_agente(origem or etapa):
            thread_id = _thread_id.get() or "sem-thread"
            inicio = time.perf_counter()
            logger.info("Componente início thread=%s etapa=%s", thread_id, etapa)
            publicar(etapa, "executando")
            try:
                parcial = no(state)
            except GraphInterrupt:
                logger.info(
                    "Componente pausado thread=%s etapa=%s motivo=gate_humano duracao_ms=%.1f",
                    thread_id,
                    etapa,
                    (time.perf_counter() - inicio) * 1000,
                )
                publicar(etapa, "pausa", "aguardando decisão humana")
                raise
            except Exception:
                logger.exception(
                    "Componente falhou thread=%s etapa=%s duracao_ms=%.1f",
                    thread_id,
                    etapa,
                    (time.perf_counter() - inicio) * 1000,
                )
                publicar(etapa, "falhou")
                raise
            logger.info(
                "Componente concluído thread=%s etapa=%s duracao_ms=%.1f %s",
                thread_id,
                etapa,
                (time.perf_counter() - inicio) * 1000,
                _resumo_saida(parcial),
            )
            publicar(etapa, "ok")
            return parcial

    return invocar


@contextmanager
def evento_ferramenta(nome: str):
    """Publica execução de ferramenta chamada dentro do contexto do grafo."""
    thread_id = _thread_id.get() or "sem-thread"
    inicio = time.perf_counter()
    logger.info("Ferramenta início thread=%s ferramenta=%s agente=%s", thread_id, nome, _origem.get() or "-")
    publicar(f"tool:{nome}", "executando")
    try:
        yield
    except GraphInterrupt:
        logger.info("Ferramenta pausada thread=%s ferramenta=%s motivo=gate_humano", thread_id, nome)
        publicar(f"tool:{nome}", "pausa")
        raise
    except Exception as exc:
        if type(exc).__name__ == "LLMError":
            logger.warning(
                "Ferramenta falhou de forma controlada thread=%s ferramenta=%s duracao_ms=%.1f erro=%s",
                thread_id,
                nome,
                (time.perf_counter() - inicio) * 1000,
                exc,
            )
        else:
            logger.exception(
                "Ferramenta falhou thread=%s ferramenta=%s duracao_ms=%.1f",
                thread_id,
                nome,
                (time.perf_counter() - inicio) * 1000,
            )
        publicar(f"tool:{nome}", "falhou")
        raise
    logger.info(
        "Ferramenta concluída thread=%s ferramenta=%s duracao_ms=%.1f",
        thread_id,
        nome,
        (time.perf_counter() - inicio) * 1000,
    )
    publicar(f"tool:{nome}", "ok")
