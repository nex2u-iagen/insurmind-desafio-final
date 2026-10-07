"""Testes TDD do contrato de agente — papel, prompt system e ferramentas por agente."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from seguramente_final.agentes.contrato import ContratoAgente
from seguramente_final.agentes.especialistas import CLASSES_ESPECIALISTAS, criar_especialistas
from seguramente_final.agentes.gate import GateHumano
from seguramente_final.agentes.nodes import (
    ComparadorNode,
    ExtratorNode,
    IngestorNode,
    PersistidorNode,
    RevisorNode,
    SintetizadorNode,
)
from seguramente_final.agentes.supervisor import SupervisorAbertura, SupervisorEncerramento
from seguramente_final.telemetria import eventos_da_thread, limpar_eventos, rodar_com_contexto
from seguramente_final.tools import ALLOWLIST, executar_ferramenta

ROOT = Path(__file__).resolve().parents[1]
POLICY_A = ROOT / "data" / "policies" / "Apolice_DO_A.pdf"

CONTRATOS_NOS = [
    SupervisorAbertura.contrato,
    SupervisorEncerramento.contrato,
    IngestorNode.contrato,
    ExtratorNode.contrato,
    ComparadorNode.contrato,
    RevisorNode.contrato,
    SintetizadorNode.contrato,
    PersistidorNode.contrato,
    GateHumano.contrato,
]


def test_contrato_exige_campos_nao_vazios():
    with pytest.raises(ValueError, match="nome"):
        ContratoAgente(nome=" ", papel="papel", prompt_sistema="prompt")
    with pytest.raises(ValueError, match="papel"):
        ContratoAgente(nome="agente", papel="", prompt_sistema="prompt")
    with pytest.raises(ValueError, match="prompt_sistema"):
        ContratoAgente(nome="agente", papel="papel", prompt_sistema="   ")


def test_contrato_rejeita_ferramenta_fora_da_allowlist():
    with pytest.raises(ValueError, match="allowlist"):
        ContratoAgente(
            nome="agente",
            papel="papel",
            prompt_sistema="prompt",
            ferramentas=frozenset({"tool_proibida"}),
        )


def test_todos_os_agentes_expoem_contrato():
    contratos = [*CONTRATOS_NOS, *(node.contrato for node in criar_especialistas().values())]
    assert len(contratos) == 15  # 9 nós + 6 especialistas
    assert len({contrato.nome for contrato in contratos}) == 15
    for contrato in contratos:
        assert contrato.nome.strip()
        assert contrato.papel.strip()
        assert contrato.prompt_sistema.strip()
        assert contrato.ferramentas <= ALLOWLIST


def test_ferramentas_por_agente_segue_a_proposta_funcional():
    assert IngestorNode.contrato.ferramentas == frozenset({"ingestar_documentos", "extrair_texto_ocr"})
    assert ExtratorNode.contrato.ferramentas == frozenset({"extrair_texto_ocr"})
    assert ComparadorNode.contrato.ferramentas == frozenset({"comparar_apolices"})
    assert SintetizadorNode.contrato.ferramentas == frozenset({"resumir_comparacao"})
    sem_ferramentas = [
        SupervisorAbertura.contrato,
        SupervisorEncerramento.contrato,
        RevisorNode.contrato,
        PersistidorNode.contrato,
        GateHumano.contrato,
        *(node.contrato for node in criar_especialistas().values()),
    ]
    for contrato in sem_ferramentas:
        assert contrato.ferramentas == frozenset()


def test_especialistas_tem_prompt_proprio_com_o_foco():
    prompts = set()
    for classe in CLASSES_ESPECIALISTAS:
        node = classe()
        assert node.foco in node.prompt_sistema
        prompts.add(node.prompt_sistema)
    assert len(prompts) == len(CLASSES_ESPECIALISTAS)


def test_executar_ferramenta_aceita_ferramenta_do_contrato():
    documentos = executar_ferramenta(IngestorNode.contrato, "ingestar_documentos", [str(POLICY_A)])
    assert len(documentos) == 1


def test_executar_ferramenta_rejeita_fora_do_contrato():
    with pytest.raises(PermissionError, match="ingestar"):
        executar_ferramenta(IngestorNode.contrato, "comparar_apolices", "a.pdf", "b.pdf")


def test_executar_ferramenta_rejeita_fora_da_allowlist():
    intruso = SimpleNamespace(nome="intruso", ferramentas=frozenset({"tool_secreta"}))
    with pytest.raises(RuntimeError, match="allowlist"):
        executar_ferramenta(intruso, "tool_secreta")


def test_evento_da_ferramenta_carrega_origem_do_agente():
    limpar_eventos("t-origem")
    rodar_com_contexto(
        "t-origem",
        lambda: executar_ferramenta(IngestorNode.contrato, "ingestar_documentos", [str(POLICY_A)]),
    )
    eventos = [e for e in eventos_da_thread("t-origem") if e["etapa"] == "tool:ingestar_documentos"]
    assert eventos
    assert all(e["origem"] == "ingestar" for e in eventos)


def test_evento_do_no_carrega_origem_da_etapa():
    from seguramente_final.telemetria import com_evento

    limpar_eventos("t-no")
    no = com_evento("comparar", lambda state: {"ok": True})
    rodar_com_contexto("t-no", lambda: no({}))
    eventos = eventos_da_thread("t-no")
    assert eventos
    assert all(e["origem"] == "comparar" for e in eventos)


def test_com_evento_aceita_origem_explicita():
    from seguramente_final.telemetria import com_evento

    limpar_eventos("t-explicita")
    no = com_evento("gate", lambda state: {"ok": True}, origem="gate_agente")
    rodar_com_contexto("t-explicita", lambda: no({}))
    assert all(e["origem"] == "gate_agente" for e in eventos_da_thread("t-explicita"))
