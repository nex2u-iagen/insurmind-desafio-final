"""Testes TDD do registro de agentes — decorator, fluxo declarativo e fábrica."""

from __future__ import annotations

from pathlib import Path

import pytest

from seguramente_final.agentes.contrato import ContratoAgente
from seguramente_final.agentes.fluxo import FANOUT, FLUXO, Contexto, construir, validar_fluxo
from seguramente_final.agentes.gate import GateHumano
from seguramente_final.agentes.nodes import IngestorNode
from seguramente_final.agentes.registro import (
    agente,
    agente_por_etapa,
    agentes_registrados,
    agrupar_por_rotulo,
    contratos_registrados,
    desregistrar,
)


def test_classe_decorada_entra_no_registro():
    try:

        @agente(rotulo="Demo", ordem=999, grupo="fila")
        class AgenteDemo:
            contrato = ContratoAgente(nome="etapa_demo", papel="demo", prompt_sistema="prompt demo")

        registro = agente_por_etapa("etapa_demo")
        assert registro.classe is AgenteDemo
        assert registro.rotulo == "Demo"
        assert registro.ordem == 999
        assert registro.grupo == "fila"
        assert registro.contrato == AgenteDemo.contrato
    finally:
        desregistrar("etapa_demo")


def test_classe_sem_contrato_levanta_erro():
    with pytest.raises(TypeError, match="contrato"):

        @agente(rotulo="Sem contrato", ordem=998)
        class AgenteSemContrato:
            pass


def test_etapa_duplicada_levanta_erro():
    with pytest.raises(ValueError, match="já registrada"):

        @agente(rotulo="Duplicado", ordem=997)
        class AgenteDuplicado:
            contrato = ContratoAgente(nome="ingestar", papel="x", prompt_sistema="y")


def test_todos_os_agentes_do_grafo_estao_registrados():
    etapas = {r.etapa for r in agentes_registrados()}
    assert etapas == {
        "supervisor_abertura",
        "supervisor_encerramento",
        "ingestar",
        "extrair",
        "comparar",
        "revisor",
        "gate",
        "sintetizar",
        "persistir",
        "especialista_identificacao",
        "especialista_limites",
        "especialista_coberturas",
        "especialista_extensoes",
        "especialista_exclusoes",
        "especialista_condicoes",
    }


def test_especialistas_registrados_com_rotulo_acentuado_e_ordem():
    especialistas = [r for r in agentes_registrados() if r.etapa.startswith("especialista_")]
    assert [r.rotulo for r in especialistas] == [
        "Identificação",
        "Limites",
        "Coberturas",
        "Extensões",
        "Exclusões",
        "Condições",
    ]
    assert [r.ordem for r in especialistas] == sorted(r.ordem for r in especialistas)


def test_agrupar_por_rotulo_monta_maestro_e_fila_do_front():
    assert agrupar_por_rotulo("maestro") == [
        ("🎩 Supervisor", ["supervisor_abertura", "supervisor_encerramento"]),
        ("⚖️ Gate humano", ["gate"]),
    ]
    fila = agrupar_por_rotulo("fila")
    assert len(fila) == 12
    assert fila[0] == ("Ingestor", ["ingestar"])
    assert ("Limites", ["especialista_limites"]) in fila
    assert fila[-1] == ("Persistidor", ["persistir"])


def test_contratos_registrados_cobre_todos_os_agentes():
    contratos = contratos_registrados()
    assert len(contratos) == 15
    assert all(isinstance(contrato, ContratoAgente) for contrato in contratos.values())
    assert contratos["gate"].nome == "gate"
    assert contratos["especialista_limites"].ferramentas == frozenset()


def test_fluxo_e_valido_e_cobre_o_registro():
    validar_fluxo(FLUXO)
    lineares = [item for item in FLUXO if item is not FANOUT]
    registrados = {r.etapa for r in agentes_registrados() if not r.etapa.startswith("especialista_")}
    assert set(lineares) == registrados
    assert len(lineares) == 9
    assert sum(1 for item in FLUXO if item is FANOUT) == 1
    assert lineares == [
        "supervisor_abertura",
        "ingestar",
        "extrair",
        "comparar",
        "revisor",
        "gate",
        "sintetizar",
        "supervisor_encerramento",
        "persistir",
    ]


def test_validar_fluxo_rejeita_fanout_invalido():
    with pytest.raises(ValueError, match="FANOUT"):
        validar_fluxo([FANOUT, "ingestar"])
    with pytest.raises(ValueError, match="FANOUT"):
        validar_fluxo(["ingestar", FANOUT])
    with pytest.raises(ValueError, match="exatamente um"):
        validar_fluxo(["ingestar", FANOUT, "comparar", FANOUT, "gate"])
    with pytest.raises(ValueError, match="duplicada"):
        validar_fluxo(["ingestar", "ingestar"])


def test_construir_instancia_com_contexto():
    extrator = object()
    ctx = Contexto(cliente="stub-cliente", extrator=extrator, diretorio=Path("/tmp/fluxo"), memoria=None)

    assert isinstance(construir("ingestar", ctx), IngestorNode)
    assert construir("extrair", ctx).extrator is extrator
    assert construir("supervisor_abertura", ctx).cliente == "stub-cliente"
    assert construir("especialista_limites", ctx).cliente == "stub-cliente"
    no_gate = construir("gate", ctx)
    assert isinstance(no_gate, GateHumano)
    assert construir("persistir", ctx).store_path == Path("/tmp/fluxo/policies.db")
