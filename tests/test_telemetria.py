"""Testes TDD da telemetria — eventos por thread para o painel da orquestra."""

from __future__ import annotations

from seguramente_final.telemetria import (
    eventos_da_thread,
    limpar_eventos,
    publicar,
    rodar_com_contexto,
)


def test_publicar_sem_contexto_nao_explode():
    publicar("qualquer_etapa", "ok")


def test_eventos_isolados_por_thread():
    limpar_eventos("t1")
    limpar_eventos("t2")
    rodar_com_contexto("t1", lambda: publicar("etapa_a", "executando"))
    rodar_com_contexto("t1", lambda: publicar("etapa_a", "ok"))
    rodar_com_contexto("t2", lambda: publicar("etapa_b", "executando"))
    eventos_t1 = eventos_da_thread("t1")
    eventos_t2 = eventos_da_thread("t2")
    assert [e["etapa"] for e in eventos_t1] == ["etapa_a", "etapa_a"]
    assert [e["status"] for e in eventos_t1] == ["executando", "ok"]
    assert [e["etapa"] for e in eventos_t2] == ["etapa_b"]


def test_evento_carrega_thread_e_ordem():
    limpar_eventos("t3")
    rodar_com_contexto("t3", lambda: publicar("gate", "executando", "pontos=2"))
    (evento,) = eventos_da_thread("t3")
    assert evento["thread_id"] == "t3"
    assert evento["detalhe"] == "pontos=2"


def test_wrapper_de_no_publica_inicio_e_fim():
    limpar_eventos("t4")

    class No:
        def __call__(self, state):
            return {"ok": True}

    from seguramente_final.telemetria import com_evento

    no = com_evento("comparar", No())
    rodar_com_contexto("t4", lambda: no({}))
    assert [e["etapa"] for e in eventos_da_thread("t4")] == ["comparar", "comparar"]
    assert [e["status"] for e in eventos_da_thread("t4")] == ["executando", "ok"]


def test_wrapper_registra_metricas_sem_logar_conteudo_documental(caplog):
    limpar_eventos("t-log")

    class No:
        def __call__(self, state):
            return {
                "fatos": [{"status": "present", "evidence": "SEGREDO DOCUMENTAL"}],
                "estatisticas_extracao": [
                    {"document_id": "doc-a", "campos": 19, "campos_llm": 1, "complemento_regras": 18, "conflitos": 0}
                ],
            }

    from seguramente_final.telemetria import com_evento

    with caplog.at_level("INFO", logger="seguramente_final.telemetria"):
        rodar_com_contexto("t-log", lambda: com_evento("extrair", No())({}))

    assert "Componente início thread=t-log etapa=extrair" in caplog.text
    assert "fatos=1[present:1]" in caplog.text
    assert "doc-a:19/19(llm=1,regras=18,conflitos=0)" in caplog.text
    assert "SEGREDO DOCUMENTAL" not in caplog.text


def test_wrapper_propaga_erro_com_status_falhou():
    limpar_eventos("t5")

    class NoRuim:
        def __call__(self, state):
            raise RuntimeError("boom")

    from seguramente_final.telemetria import com_evento

    no = com_evento("extrair", NoRuim())
    try:
        rodar_com_contexto("t5", lambda: no({}))
        raise AssertionError("deveria propagar o erro do nó")
    except RuntimeError:
        pass
    assert [e["status"] for e in eventos_da_thread("t5")] == ["executando", "falhou"]


def test_tool_registrada_publica_evento_quando_contexto_ativo():
    limpar_eventos("t6")
    from seguramente_final.tools import comparar_apolices

    raiz = __import__("pathlib").Path(__file__).resolve().parents[1]
    rodar_com_contexto(
        "t6",
        lambda: comparar_apolices(
            raiz / "data" / "policies" / "Apolice_DO_A.pdf",
            raiz / "data" / "policies" / "Apolice_DO_B.pdf",
        ),
    )
    etapas = [e["etapa"] for e in eventos_da_thread("t6")]
    assert etapas == ["tool:comparar_apolices", "tool:comparar_apolices"]
    assert [e["status"] for e in eventos_da_thread("t6")] == ["executando", "ok"]


def test_tool_sem_contexto_nao_publica():
    limpar_eventos("t7")
    from seguramente_final.tools import ingestar_documentos

    raiz = __import__("pathlib").Path(__file__).resolve().parents[1]
    ingestar_documentos([raiz / "data" / "policies" / "Apolice_DO_A.pdf"])
    assert eventos_da_thread("t7") == []
