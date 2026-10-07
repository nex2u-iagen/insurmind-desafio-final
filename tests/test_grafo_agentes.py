"""Testes TDD do grafo de agentes — e2e offline, gate com interrupt e retomada."""

from __future__ import annotations

from pathlib import Path

import pytest

from seguramente_final.agentes.orquestrador import iniciar_analise, retomar_analise
from seguramente_final.telemetria import eventos_da_thread, limpar_eventos

ROOT = Path(__file__).resolve().parents[1]
POLICY_A = ROOT / "data" / "policies" / "Apolice_DO_A.pdf"
POLICY_B = ROOT / "data" / "policies" / "Apolice_DO_B.pdf"


def test_e2e_offline_interrompe_com_pontos_e_retoma(tmp_path):
    base = tmp_path / "dados"
    resultado = iniciar_analise(
        [POLICY_A, POLICY_B],
        nomes=["Apólice A", "Apólice B"],
        pedido_usuario="compare os limites e as coberturas",
        provider_mode="offline",
        thread_id="thread-teste-1",
        diretorio=base,
    )
    assert resultado.interrompido is True
    assert resultado.pontos, "corpus com divergência material deveria gerar pontos"
    assert any(p["codigo"] == "divergencia_material" for p in resultado.pontos)
    assert "Supervisor" in resultado.mensagem

    final = retomar_analise(
        thread_id="thread-teste-1",
        decisao={"acao": "aprovado", "comentario": "ciente da divergência"},
        provider_mode="offline",
        diretorio=base,
    )
    assert final.interrompido is False
    estado = final.estado
    assert len(estado["fatos"]) == 38  # 19 campos x 2 apólices
    assert [item["campos"] for item in estado["estatisticas_extracao"]] == [19, 19]
    assert len(estado["comparacao"]) == 19
    assert estado["decisao_humana"]["acao"] == "aprovado"
    assert estado["resumo"]
    assert len(estado["achados"]) == len(estado["plano"])  # só os especialistas planejados
    assert estado["live_status"], "trace de etapas deveria existir"


def test_e2e_plano_restrito_executa_somente_os_planejados(tmp_path):
    base = tmp_path / "dados"
    pedido = "compare os limites"
    resultado = iniciar_analise(
        [POLICY_A, POLICY_B],
        nomes=["Apólice A", "Apólice B"],
        pedido_usuario=pedido,
        provider_mode="offline",
        thread_id="thread-plano-restrito",
        diretorio=base,
    )
    assert resultado.interrompido is True
    final = retomar_analise(
        thread_id="thread-plano-restrito",
        decisao={"acao": "aprovado", "comentario": "ciente"},
        provider_mode="offline",
        diretorio=base,
    )
    estado = final.estado
    assert estado["plano"] == ["limites"]
    assert [achado["especialista"] for achado in estado["achados"]] == ["limites"]
    assert estado["achados"][0]["instrucao"] == pedido
    assert estado["achados"][0]["ferramentas"] == []


def test_e2e_publica_eventos_das_tools_de_documento(tmp_path):
    base = tmp_path / "dados"
    limpar_eventos("thread-tools")
    iniciar_analise(
        [POLICY_A, POLICY_B],
        nomes=["Apólice A", "Apólice B"],
        pedido_usuario="compare coberturas",
        provider_mode="offline",
        thread_id="thread-tools",
        diretorio=base,
    )
    retomar_analise(
        thread_id="thread-tools",
        decisao={"acao": "aprovado"},
        provider_mode="offline",
        diretorio=base,
    )
    etapas = {evento["etapa"] for evento in eventos_da_thread("thread-tools")}
    assert {
        "tool:ingestar_documentos",
        "tool:comparar_apolices",
        "tool:resumir_comparacao",
    } <= etapas


def test_e2e_com_imagem_publica_evento_de_ocr(tmp_path):
    from PIL import Image, ImageDraw

    base = tmp_path / "dados"
    imagem = tmp_path / "pagina_escaneada.png"
    tela = Image.new("RGB", (640, 320), "white")
    ImageDraw.Draw(tela).text((20, 140), "Limite maximo de responsabilidade", fill="black")
    tela.save(imagem)

    limpar_eventos("thread-ocr")
    resultado = iniciar_analise(
        [imagem, POLICY_B],
        nomes=["Página digitalizada", "Apólice B"],
        provider_mode="offline",
        thread_id="thread-ocr",
        diretorio=base,
    )
    if resultado.interrompido:
        retomar_analise(
            thread_id="thread-ocr",
            decisao={"acao": "aprovado"},
            provider_mode="offline",
            diretorio=base,
        )
    etapas = {evento["etapa"] for evento in eventos_da_thread("thread-ocr")}
    assert "tool:ingestar_documentos" in etapas
    assert "tool:extrair_texto_ocr" in etapas


def test_e2e_sem_pontos_nao_interrompe(tmp_path):
    """Arquivos distintos com o mesmo conteúdo não geram pontos nem interrompem o gate."""
    base = tmp_path / "dados"
    copia = tmp_path / "Apolice_DO_A__copia.pdf"
    copia.write_bytes(POLICY_A.read_bytes() + b"\n% copia byte a byte\n")
    resultado = iniciar_analise(
        [POLICY_A, copia],
        nomes=["Apólice A", "Apólice A (cópia)"],
        provider_mode="offline",
        thread_id="thread-teste-2",
        diretorio=base,
    )
    assert resultado.interrompido is False
    assert resultado.pontos == []
    assert len(resultado.estado["comparacao"]) == 19


def test_mesmo_arquivo_nas_duas_posicoes_erro_claro(tmp_path):
    """Mesmo arquivo duas vezes = mesmo SHA-256; a análise falha cedo com mensagem clara."""
    base = tmp_path / "dados"
    with pytest.raises(ValueError, match="mesmo arquivo"):
        iniciar_analise(
            [POLICY_A, POLICY_A],
            nomes=["Apólice A", "Apólice A"],
            provider_mode="offline",
            thread_id="thread-duplicado",
            diretorio=base,
        )


def test_estado_persistido_em_checkpoints(tmp_path):
    base = tmp_path / "dados"
    iniciar_analise(
        [POLICY_A, POLICY_B],
        provider_mode="offline",
        thread_id="thread-teste-3",
        diretorio=base,
    )
    arquivos = list((base / "checkpoints" / "thread-teste-3").glob("*.ckpt.json"))
    assert arquivos, "epochDBCheckpointer deveria gravar checkpoint JSON"


def test_memoria_e_auditoria_gravados(tmp_path):
    base = tmp_path / "dados"
    iniciar_analise([POLICY_A, POLICY_B], provider_mode="offline", thread_id="t-aud", diretorio=base)
    auditoria = list((base / "evidence").glob("gate_audit_*.jsonl"))
    assert auditoria, "decisão do gate deveria ser auditada em JSONL"
    retomar_analise(thread_id="t-aud", decisao={"acao": "aprovado"}, provider_mode="offline", diretorio=base)
    memorias = base / "memoria" / "registros.jsonl"
    assert memorias.exists(), "análise concluída deveria ser lembrada na memória de longo prazo"


def test_iniciar_analise_leva_simular_ocr_para_o_estado(monkeypatch, tmp_path):
    from seguramente_final.agentes import orquestrador

    class _GrafoFalso:
        def __init__(self) -> None:
            self.estado: dict | None = None

        def invoke(self, estado, config=None):
            self.estado = estado
            return {"mensagem_supervisor": "ok"}

    grafo = _GrafoFalso()
    monkeypatch.setattr(orquestrador, "montar_grafo", lambda **kwargs: grafo)
    iniciar_analise(
        [POLICY_A, POLICY_B],
        provider_mode="offline",
        simular_ocr=True,
        thread_id="t-sim-ocr",
        diretorio=tmp_path,
    )
    assert grafo.estado is not None
    assert grafo.estado["simular_ocr"] is True


def test_iniciar_analise_sem_simular_ocr_default_false(monkeypatch, tmp_path):
    from seguramente_final.agentes import orquestrador

    class _GrafoFalso:
        def __init__(self) -> None:
            self.estado: dict | None = None

        def invoke(self, estado, config=None):
            self.estado = estado
            return {"mensagem_supervisor": "ok"}

    grafo = _GrafoFalso()
    monkeypatch.setattr(orquestrador, "montar_grafo", lambda **kwargs: grafo)
    iniciar_analise([POLICY_A, POLICY_B], provider_mode="offline", thread_id="t-sem-sim", diretorio=tmp_path)
    assert grafo.estado is not None
    assert grafo.estado["simular_ocr"] is False


def test_ingestor_node_repassa_simular_ocr_do_estado(monkeypatch):
    from seguramente_final.agentes import nodes

    capturas: dict = {}

    def _exec_falso(agente, nome, *args, **kwargs):
        capturas["kwargs"] = kwargs
        return [{"document_id": "FAKE", "name": "A"}]

    monkeypatch.setattr(nodes, "executar_ferramenta", _exec_falso)
    saida = nodes.IngestorNode()({"caminhos": ["a.pdf"], "nomes": ["A"], "simular_ocr": True})
    assert capturas["kwargs"]["forcar_ocr"] is True
    assert saida["documentos"]


def test_e2e_com_simular_ocr_publica_evento_de_ocr_em_pdf_textual(tmp_path, monkeypatch):
    from seguramente_final.tools.ocr import OcrEngine

    monkeypatch.setattr(OcrEngine, "reconhecer_pagina_pdf", lambda self, path, page_number: "")
    base = tmp_path / "dados"
    limpar_eventos("thread-sim-ocr")
    resultado = iniciar_analise(
        [POLICY_A, POLICY_B],
        nomes=["Apólice A", "Apólice B"],
        provider_mode="offline",
        simular_ocr=True,
        thread_id="thread-sim-ocr",
        diretorio=base,
    )
    if resultado.interrompido:
        retomar_analise(
            thread_id="thread-sim-ocr",
            decisao={"acao": "aprovado"},
            provider_mode="offline",
            diretorio=base,
        )
    etapas = {evento["etapa"] for evento in eventos_da_thread("thread-sim-ocr")}
    assert "tool:ingestar_documentos" in etapas
    assert "tool:extrair_texto_ocr" in etapas


def test_sintetizador_repassa_memoria_contexto_para_a_tool(monkeypatch):
    from seguramente_final.agentes import nodes

    capturas: dict = {}

    def _exec_falso(agente, nome, *args, **kwargs):
        capturas["args"] = args
        return "resumo"

    monkeypatch.setattr(nodes, "executar_ferramenta", _exec_falso)
    saida = nodes.SintetizadorNode()({"comparacao": [], "memoria_contexto": ["registro antigo"]})
    assert saida["resumo"] == "resumo"
    assert saida["fallback_resumo"] is False
    assert capturas["args"][-1] == ["registro antigo"]


def test_fabrica_do_ingestor_recebe_a_memoria_documental():
    from seguramente_final.agentes.fluxo import FABRICAS, Contexto

    class MemoriaFake:
        pass

    memoria = MemoriaFake()
    node = FABRICAS["ingestar"](Contexto(memoria=memoria))
    assert node.memoria is memoria


def test_ingestor_encaminha_paginas_extraidas_ao_indice(monkeypatch):
    from seguramente_final.agentes import nodes

    documentos = [
        {"document_id": "doc-a", "pages": [{"page_number": 1, "text": "texto PDF"}]},
        {"document_id": "doc-b", "pages": [{"page_number": 2, "text": "texto OCR"}]},
    ]

    class MemoriaIndexadora:
        def __init__(self) -> None:
            self.documentos = None

        def indexar_documentos(self, documentos_recebidos):
            self.documentos = documentos_recebidos
            return {"available": True, "indexed_pages": 2, "skipped_pages": 0}

    memoria = MemoriaIndexadora()
    monkeypatch.setattr(nodes, "executar_ferramenta", lambda *args, **kwargs: documentos)
    saida = nodes.IngestorNode(memoria)({"caminhos": ["a.pdf", "b.pdf"]})

    assert memoria.documentos == documentos
    assert saida["indexacao_documental"]["indexed_pages"] == 2
    assert "2 página(s) indexada(s)" in saida["live_status"][0]["detalhe"]


def test_sintetizador_sinaliza_fallback_quando_resumo_llm_falha(monkeypatch):
    from seguramente_final.agentes import nodes
    from seguramente_final.motor_llm import LLMError

    def _falha(agente, nome, *args, **kwargs):
        raise LLMError("provedor indisponível")

    monkeypatch.setattr(nodes, "executar_ferramenta", _falha)
    saida = nodes.SintetizadorNode()({"comparacao": []})
    assert saida["fallback_resumo"] is True
    assert isinstance(saida["resumo"], str) and saida["resumo"]


def test_sintetizador_repassa_motivo_quando_extrator_ja_degradou(monkeypatch):
    """O motivo do extrator prevalece; o sintetizador só completa quando ausente."""
    from seguramente_final.agentes import nodes
    from seguramente_final.motor_llm import LLMError

    monkeypatch.setattr(nodes, "executar_ferramenta", lambda *a, **k: (_ for _ in ()).throw(LLMError("sem cota")))
    sem_motivo = nodes.SintetizadorNode()({"comparacao": []})
    assert sem_motivo["motivo_degradacao"] == "sem cota"
    # Com motivo já presente, o nó não devolve a chave: no LangGraph o valor do
    # extrator permanece no estado (merge por campo, sem sobrescrita vazia).
    com_motivo = nodes.SintetizadorNode()({"comparacao": [], "motivo_degradacao": "cota esgotada no extrator"})
    assert "motivo_degradacao" not in com_motivo
    assert com_motivo["fallback_resumo"] is True
