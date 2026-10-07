"""Orquestração do grafo — iniciar análise (interrupt) e retomar com decisão humana."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langgraph.types import Command

from ..motor_llm import criar_cliente
from ..rules import RuleBasedExtractor
from ..telemetria import rodar_com_contexto
from ..tools.extrator import ExtratorLLM
from .grafo import montar_grafo

logger = logging.getLogger(__name__)


@dataclass
class ResultadoAnalise:
    """Resultado da invocação do grafo (parcial no interrupt, completo na retomada)."""

    thread_id: str
    interrompido: bool
    pontos: list[dict[str, Any]] = field(default_factory=list)
    mensagem: str = ""
    estado: dict[str, Any] = field(default_factory=dict)


def _fabricar(provider_mode: str, modelo: str | None, api_key: str | None) -> tuple[Any, Any]:
    """Extrator e cliente conforme o modo: offline determinístico ou provedor LLM."""
    if provider_mode == "offline":
        return RuleBasedExtractor(), None
    cliente = criar_cliente(provider_mode, model=modelo, api_key=api_key)
    return ExtratorLLM(cliente=cliente), cliente


def iniciar_analise(
    caminhos: Iterable[str | Path],
    nomes: list[str] | None = None,
    pedido_usuario: str = "",
    provider_mode: str = "offline",
    modelo: str | None = None,
    api_key: str | None = None,
    thread_id: str | None = None,
    diretorio: str | Path | None = None,
    simular_ocr: bool = False,
) -> ResultadoAnalise:
    """Executa o grafo até o gate humano (ou até o fim, quando não há pontos).

    Args:
        caminhos: Duas apólices (PDF ou imagem).
        nomes: Nomes de exibição alinhados a ``caminhos``.
        pedido_usuario: Pedido livre do usuário para o supervisor.
        provider_mode: ``offline``, ``openai``, ``groq`` ou ``google``.
        modelo: Modelo específico do provedor (default do provedor).
        api_key: Chave informada pelo usuário no front (não persiste no estado).
        thread_id: Identificador da thread de checkpoint (gerado quando ausente).
        diretorio: Raiz de dados (default ``data``).
        simular_ocr: Aciona o OCR também em PDFs com texto nativo (visão no painel).

    Returns:
        :class:`ResultadoAnalise` com ``interrompido``, ``pontos`` e ``mensagem``.

    Raises:
        ValueError: Menos de duas apólices.
        LLMError: Falha de chamada no modo LLM.
    """
    caminho_lista = [str(c) for c in caminhos]
    if len(caminho_lista) < 2:
        raise ValueError("A comparação exige pelo menos duas apólices.")
    diretorio_efetivo = Path(diretorio or "data")
    thread_efetivo = thread_id or uuid.uuid4().hex[:12]
    extrator, cliente = _fabricar(provider_mode, modelo, api_key)
    logger.info(
        "Análise iniciada thread=%s documentos=%s provider=%s modelo=%s",
        thread_efetivo,
        len(caminho_lista),
        provider_mode,
        modelo or getattr(cliente, "model", "") or "",
    )
    grafo = montar_grafo(extrator=extrator, cliente=cliente, diretorio=diretorio_efetivo, provider_mode=provider_mode)
    estado_inicial: dict[str, Any] = {
        "thread_id": thread_efetivo,
        "caminhos": caminho_lista,
        "nomes": list(nomes or []),
        "pedido_usuario": pedido_usuario or "",
        "provedor": provider_mode,
        "modelo": modelo or getattr(cliente, "model", "") or "",
        "simular_ocr": bool(simular_ocr),
    }
    saida = rodar_com_contexto(
        thread_efetivo,
        lambda: grafo.invoke(estado_inicial, config={"configurable": {"thread_id": thread_efetivo}}),
    )
    return _resultado(thread_efetivo, saida)


def retomar_analise(
    thread_id: str,
    decisao: dict[str, Any],
    provider_mode: str = "offline",
    modelo: str | None = None,
    api_key: str | None = None,
    diretorio: str | Path | None = None,
) -> ResultadoAnalise:
    """Retoma a thread interrompida com a decisão humana (``Command(resume=...)``).

    Args:
        thread_id: Thread de checkpoint criada em :func:`iniciar_analise`.
        decisao: Payload da decisão (ex.: ``{"acao": "aprovado", "comentario": "..."}``).
        provider_mode: Mesmo modo usado na invocação inicial.
        modelo: Modelo específico do provedor.
        api_key: Chave informada pelo usuário (não persiste no estado).
        diretorio: Raiz de dados (default ``data``).

    Returns:
        :class:`ResultadoAnalise` final (sem interrupção).
    """
    diretorio_efetivo = Path(diretorio or "data")
    extrator, cliente = _fabricar(provider_mode, modelo, api_key)
    logger.info(
        "Análise retomada thread=%s provider=%s modelo=%s decisão=%s",
        thread_id,
        provider_mode,
        modelo or getattr(cliente, "model", "") or "",
        decisao.get("acao", "sem_acao"),
    )
    grafo = montar_grafo(extrator=extrator, cliente=cliente, diretorio=diretorio_efetivo, provider_mode=provider_mode)
    saida = rodar_com_contexto(
        thread_id,
        lambda: grafo.invoke(Command(resume=decisao), config={"configurable": {"thread_id": thread_id}}),
    )
    return _resultado(thread_id, saida)


def _resultado(thread_id: str, saida: dict[str, Any]) -> ResultadoAnalise:
    """Converte a saída do invoke (com ou sem ``__interrupt__``) no resultado."""
    interruptos = saida.get("__interrupt__") or ()
    if interruptos:
        valor = interruptos[0].value
        logger.info("Gate acionado na thread %s: %s ponto(s)", thread_id, len(valor.get("pontos", [])))
        return ResultadoAnalise(
            thread_id=thread_id,
            interrompido=True,
            pontos=list(valor.get("pontos", [])),
            mensagem=str(valor.get("mensagem", "")),
            estado=saida,
        )
    resultado = ResultadoAnalise(
        thread_id=thread_id,
        interrompido=False,
        mensagem=str(saida.get("mensagem_supervisor", "")),
        estado=saida,
    )
    logger.info(
        "Análise finalizada thread=%s documentos=%s fatos=%s comparações=%s fallback_extrator=%s fallback_resumo=%s",
        thread_id,
        len(saida.get("documentos") or []),
        len(saida.get("fatos") or []),
        len(saida.get("comparacao") or []),
        bool(saida.get("fallback_extrator")),
        bool(saida.get("fallback_resumo")),
    )
    return resultado
