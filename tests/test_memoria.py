"""Testes TDD da memória — fonte epochDB (config, consulta roundtrip) e composição."""

from __future__ import annotations

import importlib.util
import sys
import types

import pytest

from seguramente_final.agentes.memoria import (
    MemoriaComposta,
    MemoriaEpochDb,
    criar_memoria,
)


def _epochdb_falso(monkeypatch, captura: dict, atoms: list | None = None):
    """Instala um stub do pacote ``epochdb`` capturando kwargs/consultas."""
    modulo = types.ModuleType("epochdb")

    class EpochDB:
        def __init__(self, **kwargs) -> None:
            captura.update(kwargs)

        def recall_text(self, pergunta: str, top_k: int = 5, **kwargs):
            captura["consulta"] = (pergunta, top_k)
            return atoms or []

    modulo.EpochDB = EpochDB
    monkeypatch.setitem(sys.modules, "epochdb", modulo)
    return EpochDB


def test_tentar_criar_configura_modelo_local_e_extracao_offline(monkeypatch, tmp_path):
    captura: dict = {}
    _epochdb_falso(monkeypatch, captura)
    fonte = MemoriaEpochDb.tentar_criar(tmp_path / "epoch")
    assert isinstance(fonte, MemoriaEpochDb)
    assert captura["model"] == "all-MiniLM-L6-v2"
    assert captura["storage_dir"] == str(tmp_path / "epoch")
    assert captura["auto_extract"] is True
    assert captura["extraction_model"] == "local"


def test_tentar_criar_respeita_variaveis_de_ambiente(monkeypatch, tmp_path):
    captura: dict = {}
    _epochdb_falso(monkeypatch, captura)
    monkeypatch.setenv("SEGURAMENTE_EMBEDDING", "google:gemini-embedding-001")
    monkeypatch.setenv("EPOCHDB_EXTRACTION_MODEL", "google:gemini-2.5-flash")
    fonte = MemoriaEpochDb.tentar_criar(tmp_path / "epoch")
    assert fonte is not None
    assert captura["model"] == "google:gemini-embedding-001"
    assert captura["extraction_model"] == "google:gemini-2.5-flash"


def test_tentar_criar_devolve_none_quando_epochdb_indisponivel(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "epochdb", None)
    assert MemoriaEpochDb.tentar_criar(tmp_path / "epoch") is None


def test_query_epochdb_usa_recall_text_e_extrai_payload(monkeypatch, tmp_path):
    captura: dict = {}
    atoms = [types.SimpleNamespace(payload="registro antigo"), types.SimpleNamespace(payload="outro registro")]
    _epochdb_falso(monkeypatch, captura, atoms=atoms)
    fonte = MemoriaEpochDb.tentar_criar(tmp_path / "epoch")
    textos = fonte.query("compare limites", k=2)
    assert captura["consulta"] == ("compare limites", 2)
    assert textos == ["registro antigo", "outro registro"]


def test_epochdb_indexa_paginas_com_metadados_triplas_e_sem_duplicar(monkeypatch, tmp_path):
    captura: dict = {"memorias": []}
    modulo = types.ModuleType("epochdb")

    class EpochDB:
        def __init__(self, **kwargs) -> None:
            captura.update(kwargs)

        def remember(self, texto, metadata=None, triples=None, atom_id=None, **kwargs) -> None:
            captura["memorias"].append(
                {"text": texto, "metadata": metadata or {}, "triples": triples or [], "atom_id": atom_id}
            )

        def query(self, pergunta, k=5, filters=None, **kwargs):
            captura.setdefault("consultas", []).append({"pergunta": pergunta, "k": k, "filters": filters, **kwargs})
            document_ids = filters["document_id"]["$in"]
            return [
                types.SimpleNamespace(text=item["text"], metadata=item["metadata"])
                for item in captura["memorias"]
                if item["metadata"]["document_id"] in document_ids and item["metadata"]["kind"] == "document_page"
            ]

    modulo.EpochDB = EpochDB
    monkeypatch.setitem(sys.modules, "epochdb", modulo)
    memoria = MemoriaEpochDb.tentar_criar(tmp_path / "epoch")
    documentos = [
        {
            "document_id": "doc-a",
            "name": "Apólice A",
            "pages": [{"page_number": 2, "text": "Limite de R$ 10 milhões", "extraction_method": "pdf-text"}],
        },
        {
            "document_id": "doc-b",
            "name": "Apólice B",
            "pages": [{"page_number": 4, "text": "Limite de R$ 15 milhões", "extraction_method": "ocr"}],
        },
    ]

    primeira = memoria.indexar_documentos(documentos)
    segunda = memoria.indexar_documentos(documentos)
    trechos = memoria.recuperar_trechos("compare limites", ["doc-a", "doc-b"])

    assert primeira == {"available": True, "indexed_pages": 2, "skipped_pages": 0}
    assert segunda == {"available": True, "indexed_pages": 0, "skipped_pages": 2}
    assert len(captura["memorias"]) == 2
    assert captura["memorias"][0]["metadata"]["page_number"] == 2
    assert ("doc-a", "has_page", "doc-a:pagina:2") in captura["memorias"][0]["triples"]
    assert [consulta["filters"]["document_id"]["$in"] for consulta in captura["consultas"]] == [
        ["doc-a"],
        ["doc-b"],
    ]
    assert all(consulta["k"] == 2 for consulta in captura["consultas"])
    assert all(consulta["filters"]["kind"] == "document_page" for consulta in captura["consultas"])
    assert all(consulta["filters"]["chunk_id"]["$in"] for consulta in captura["consultas"])
    assert {(trecho["document_id"], trecho["page_number"]) for trecho in trechos} == {("doc-a", 2), ("doc-b", 4)}
    assert all("[DOCUMENTO" not in trecho["text"] for trecho in trechos)


def test_memoria_local_nao_se_apresenta_como_indice_vetorial(tmp_path):
    from seguramente_final.agentes.memoria import MemoriaLocal

    memoria = MemoriaLocal(tmp_path / "registros.jsonl")
    assert memoria.indexar_documentos([])["available"] is False
    assert memoria.recuperar_trechos("limites", ["doc-a"]) == []


def test_criar_memoria_compoe_epochdb_e_local(monkeypatch, tmp_path):
    captura: dict = {}
    _epochdb_falso(monkeypatch, captura)
    memoria = criar_memoria(tmp_path)
    assert isinstance(memoria, MemoriaComposta)
    assert len(memoria.fontes) == 2


def test_smoke_epochdb_real_roundtrip_remember_e_query(tmp_path):
    """Roundtrip real (skip quando hnswlib/toolchain ausente)."""
    if importlib.util.find_spec("hnswlib") is None:
        pytest.skip("hnswlib ausente (instale gcc-c++/python3-devel e pip install hnswlib)")
    fonte = MemoriaEpochDb.tentar_criar(tmp_path / "epoch")
    if fonte is None:
        pytest.skip("epochDB indisponível neste ambiente")
    fonte.remember(
        "Análise smoke: limite máximo de responsabilidade divergiu entre as apólices.",
        metadata={"thread_id": "smoke"},
        triples=[("apólice-a", "limite", "10.000.000")],
    )
    textos = fonte.query("limite máximo de responsabilidade", k=1)
    assert textos, "epochDB deveria recuperar o registro lembrado"
    assert "limite" in textos[0]


def test_memoria_local_query_por_termos_relevante(tmp_path):
    from seguramente_final.agentes.memoria import MemoriaLocal

    memoria = MemoriaLocal(tmp_path / "registros.jsonl")
    memoria.remember("Análise t1: A vs B — assuntos: limites, coberturas; resumo: divergência de limites.")
    memoria.remember("Análise t2: A vs C — assuntos: exclusoes; resumo: cláusula de exclusão ampla.")
    resultados = memoria.query("compare os limites de responsabilidade")
    assert resultados and "limites" in resultados[0]
    assert len(resultados) == 1  # t2 não compartilha termos relevantes
    assert memoria.query("zzz termo inexistente") == []


def test_persistidor_registra_assuntos_como_triplas(tmp_path):
    from pathlib import Path

    from seguramente_final.agentes.nodes import PersistidorNode
    from seguramente_final.ingest import load_document

    root = Path(__file__).resolve().parents[1]
    docs = [
        load_document(root / "data/policies/Apolice_DO_A.pdf", name="A").to_dict(),
        load_document(root / "data/policies/Apolice_DO_B.pdf", name="B").to_dict(),
    ]
    linhas = [
        {
            "category": "limites",
            "label": "Limite máximo",
            "policy_a": "10.000.000",
            "policy_b": "15.000.000",
            "difference": "5.000.000",
            "status": "diferente",
            "evidence_a": "a",
            "evidence_b": "b",
            "page_a": 1,
            "page_b": 1,
        },
        {
            "category": "coberturas",
            "label": "Defesa",
            "policy_a": "sim",
            "policy_b": "sim",
            "difference": "",
            "status": "igual",
            "evidence_a": "a",
            "evidence_b": "b",
            "page_a": 2,
            "page_b": 2,
        },
    ]

    class MemoriaCaptura:
        def __init__(self) -> None:
            self.registros: list[dict] = []

        def remember(self, texto, metadata=None, triples=None) -> None:
            self.registros.append({"texto": texto, "metadata": metadata or {}, "triples": triples or []})

        def query(self, pergunta, k=3):
            return []

    memoria = MemoriaCaptura()
    PersistidorNode(tmp_path / "policies.db", memoria)(
        {"thread_id": "t-b", "documentos": docs, "comparacao": linhas, "resumo": "resumo", "provedor": "offline"}
    )
    assert memoria.registros
    registro = memoria.registros[0]
    assert "assuntos: limites" in registro["texto"]  # categorias com diferença no texto
    assert "coberturas" not in registro["texto"]  # linha igual não vira assunto
    assert registro["metadata"]["assuntos"] == ["limites"]
    assert ("t-b", "aborda", "limites") in registro["triples"]
    assert ("t-b", "aborda", "coberturas") not in registro["triples"]
    id_a, id_b = docs[0]["document_id"], docs[1]["document_id"]
    assert (id_a, "compara_com", id_b) in registro["triples"]


def test_bloco_memoria_limita_quantidade_e_tamanho():
    from seguramente_final.prompting import bloco_memoria

    contexto = ["registro " + "x" * 1000] * 5
    bloco = bloco_memoria(contexto)
    assert bloco.startswith("Análises anteriores")
    assert bloco.count("- ") == 3  # no máximo 3 lembranças
    assert "x" * 501 not in bloco  # cada lembrança truncada em 500 caracteres
    assert bloco_memoria([]) == ""
    assert bloco_memoria(None) == ""


def _epochdb_com_flush(monkeypatch, captura: dict):
    """Stub do epochDB com ``wait_for_extractions``/``flush`` contabilizados."""

    class EpochDB:
        def __init__(self, **kwargs) -> None:
            captura.update(kwargs)

        def remember(self, texto, **kwargs) -> None:
            captura["texto"] = texto

        def recall_text(self, pergunta, top_k=5, **kwargs):
            return []

        def wait_for_extractions(self, timeout=None) -> None:
            captura["esperou"] = timeout

        def flush(self) -> None:
            captura["flush"] = captura.get("flush", 0) + 1

    modulo = types.ModuleType("epochdb")
    modulo.EpochDB = EpochDB
    monkeypatch.setitem(sys.modules, "epochdb", modulo)
    return EpochDB


def test_epochdb_finalizar_aguarda_extracoes_e_faz_flush(monkeypatch, tmp_path):
    captura: dict = {}
    _epochdb_com_flush(monkeypatch, captura)
    fonte = MemoriaEpochDb.tentar_criar(tmp_path / "epoch")
    fonte.finalizar()
    assert captura["esperou"] is not None  # WAL nunca checkpointado sem isto
    assert captura["flush"] == 1


def test_epochdb_finalizar_engole_erro_de_flush(monkeypatch, tmp_path):
    captura: dict = {}
    _epochdb_com_flush(monkeypatch, captura)
    fonte = MemoriaEpochDb.tentar_criar(tmp_path / "epoch")

    def _flush_quebrado() -> None:
        raise RuntimeError("disco cheio")

    fonte.db.flush = _flush_quebrado  # type: ignore[attr-defined]
    fonte.finalizar()  # não deve levantar: análise já concluída


def test_memoria_local_finalizar_e_no_op(tmp_path):
    from seguramente_final.agentes.memoria import MemoriaLocal

    memoria = MemoriaLocal(tmp_path / "registros.jsonl")
    memoria.remember("registro")
    memoria.finalizar()  # não levanta nem precisa de nada


def test_memoria_composta_finaliza_cada_fonte():
    class Fonte:
        def __init__(self, quebrar=False) -> None:
            self.finalizacoes = 0
            self.quebrar = quebrar

        def finalizar(self) -> None:
            self.finalizacoes += 1
            if self.quebrar:
                raise RuntimeError("falha na fonte")

    class FonteLegada:
        """Fonte antiga (só remember/query): não pode quebrar a composição."""

        def remember(self, texto, metadata=None, triples=None) -> None:
            pass

        def query(self, pergunta, k=3):
            return []

    ok, quebrada = Fonte(), Fonte(quebrar=True)
    composta = MemoriaComposta([ok, quebrada, FonteLegada()])  # type: ignore[arg-type]
    composta.finalizar()  # a falha de uma fonte não impede as demais
    assert ok.finalizacoes == 1
    assert quebrada.finalizacoes == 1


def test_persistidor_chama_finalizar_apos_remember(tmp_path):
    from seguramente_final.agentes.nodes import PersistidorNode

    class MemoriaCaptura:
        def __init__(self) -> None:
            self.chamadas: list[str] = []

        def remember(self, texto, metadata=None, triples=None) -> None:
            self.chamadas.append("remember")

        def query(self, pergunta, k=3):
            return []

        def finalizar(self) -> None:
            self.chamadas.append("finalizar")

    memoria = MemoriaCaptura()
    PersistidorNode(tmp_path / "policies.db", memoria)(
        {"thread_id": "t-fin", "documentos": [], "comparacao": [], "resumo": "r", "provedor": "offline"}
    )
    assert memoria.chamadas == ["remember", "finalizar"]
