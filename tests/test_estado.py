"""Testes TDD do estado do grafo — serialização JSON-safe e live_status em lote."""

from __future__ import annotations

import json
from pathlib import Path

from seguramente_final.agentes.estado import (
    adicionar_live_status,
    novo_status,
    reidratar_documento,
    serializar_documento,
)
from seguramente_final.ingest import load_document

ROOT = Path(__file__).resolve().parents[1]
POLICY_A = ROOT / "data" / "policies" / "Apolice_DO_A.pdf"


def test_serializacao_documento_e_json_safe():
    doc = load_document(POLICY_A, name="A")
    dados = serializar_documento(doc)
    json.dumps(dados)
    assert dados["document_id"] == doc.document_id
    assert len(dados["pages"]) == 3


def test_reidratar_documento_preserva_identidade_e_paginas():
    doc = load_document(POLICY_A, name="A")
    reidratado = reidratar_documento(serializar_documento(doc))
    assert reidratado.document_id == doc.document_id
    assert reidratado.name == doc.name
    assert len(reidratado.pages) == 3
    assert reidratado.pages[0].text == doc.pages[0].text


def test_adicionar_live_status_concatena_em_lote():
    estado = {"live_status": [novo_status("supervisor_abertura", "supervisor")]}
    entradas = [novo_status("ingestar", "ingestor"), novo_status("extrair", "extrator")]
    atualizado = adicionar_live_status(estado, entradas)
    assert [item["etapa"] for item in atualizado] == ["supervisor_abertura", "ingestar", "extrair"]
    assert estado["live_status"] == [novo_status("supervisor_abertura", "supervisor")]
