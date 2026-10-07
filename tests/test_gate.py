"""Testes TDD do gate humano — regras de pontos críticos e auditoria."""

from __future__ import annotations

import json

from seguramente_final.agentes.gate import calcular_pontos_criticos, registrar_auditoria


def _linha(**kwargs) -> dict:
    base = {
        "category": "coberturas",
        "label": "Cobertura A — indenização ao segurado",
        "policy_a": "Sim",
        "policy_b": "Sim",
        "difference": "",
        "status": "igual",
        "evidence_a": "COBERTURA A: Sim",
        "evidence_b": "COBERTURA A: Sim",
        "page_a": 1,
        "page_b": 1,
    }
    base.update(kwargs)
    return base


def _fato(**kwargs) -> dict:
    base = {
        "document_id": "ABC",
        "category": "limites",
        "label": "Limite máximo de responsabilidade",
        "value": "R$ 10.000.000,00",
        "status": "present",
        "confidence": 0.98,
        "page": 2,
        "evidence": "LIMITE MÁXIMO: R$ 10.000.000,00",
        "normalized_value": "brl 10.000.000,00",
        "source": "teste",
    }
    base.update(kwargs)
    return base


def _estado(**kwargs) -> dict:
    base = {
        "documentos": [
            {"pages": [{"page_number": 1, "text": "ok", "extraction_method": "pdf-text"}]},
            {"pages": [{"page_number": 1, "text": "ok", "extraction_method": "pdf-text"}]},
        ],
        "fatos": [_fato(), _fato()],
        "comparacao": [_linha()],
        "fallback_extrator": False,
    }
    base.update(kwargs)
    return base


def test_estado_limpo_nao_gera_pontos():
    assert calcular_pontos_criticos(_estado()) == []


def test_ambiguidade_gera_ponto():
    pontos = calcular_pontos_criticos(_estado(comparacao=[_linha(status="ambigua")]))
    assert [p["codigo"] for p in pontos] == ["ambiguidade"]
    assert pontos[0]["severidade"] == "alta"


def test_ausente_em_so_uma_apolice_em_campo_critico_gera_ponto():
    pontos = calcular_pontos_criticos(_estado(comparacao=[_linha(status="ausente_em_b", policy_b=None)]))
    assert "ausente_critico" in [p["codigo"] for p in pontos]


def test_ausente_em_campo_nao_critico_nao_gera_ponto():
    linha = _linha(label="Poluição", category="exclusoes", status="ausente_em_b", policy_b=None)
    assert calcular_pontos_criticos(_estado(comparacao=[linha])) == []


def test_pagina_sem_extracao_gera_ponto():
    documentos = [
        {"pages": [{"page_number": 1, "text": "", "extraction_method": "ocr-empty"}]},
        {"pages": [{"page_number": 1, "text": "ok", "extraction_method": "pdf-text"}]},
    ]
    pontos = calcular_pontos_criticos(_estado(documentos=documentos))
    assert "extracao_falhou" in [p["codigo"] for p in pontos]


def test_fato_present_sem_evidencia_gera_ponto():
    fatos = [_fato(evidence="", page=None)]
    pontos = calcular_pontos_criticos(_estado(fatos=fatos))
    assert "sem_evidencia" in [p["codigo"] for p in pontos]


def test_divergencia_material_acima_de_20_por_cento_gera_ponto():
    linha = _linha(
        label="Limite máximo de responsabilidade",
        category="limites",
        status="diferente",
        policy_a="R$ 10.000.000,00",
        policy_b="R$ 15.000.000,00",
    )
    pontos = calcular_pontos_criticos(_estado(comparacao=[linha]))
    assert "divergencia_material" in [p["codigo"] for p in pontos]
    ponto = next(p for p in pontos if p["codigo"] == "divergencia_material")
    assert "50" in ponto["detalhe"]


def test_divergencia_pequena_nao_gera_ponto():
    linha = _linha(
        label="Limite máximo de responsabilidade",
        category="limites",
        status="diferente",
        policy_a="R$ 10.000.000,00",
        policy_b="R$ 11.000.000,00",
    )
    assert calcular_pontos_criticos(_estado(comparacao=[linha])) == []


def test_fallback_do_extrator_llm_gera_ponto():
    pontos = calcular_pontos_criticos(_estado(fallback_extrator=True))
    assert "fallback_extrator" in [p["codigo"] for p in pontos]


def test_registrar_auditoria_grava_jsonl(tmp_path):
    arquivo = tmp_path / "gate.jsonl"
    registrar_auditoria(
        thread_id="t-1",
        pontos=[{"codigo": "ambiguidade"}],
        decisao={"acao": "aprovado", "comentario": "ok"},
        caminho=arquivo,
    )
    registros = [json.loads(linha) for linha in arquivo.read_text(encoding="utf-8").splitlines()]
    assert registros[0]["thread_id"] == "t-1"
    assert registros[0]["decisao"]["acao"] == "aprovado"
    assert registros[0]["pontos"][0]["codigo"] == "ambiguidade"
    assert registros[0]["actor"] == "humano"
