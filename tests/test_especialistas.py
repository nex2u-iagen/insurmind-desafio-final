"""Testes TDD dos especialistas — uma classe individual por área de domínio."""

from __future__ import annotations

from seguramente_final.agentes.especialistas import (
    CLASSES_ESPECIALISTAS,
    EspecialistaCoberturas,
    EspecialistaCondicoes,
    EspecialistaExclusoes,
    EspecialistaExtensoes,
    EspecialistaIdentificacao,
    EspecialistaLimites,
    EspecialistaNode,
    criar_especialistas,
)
from seguramente_final.agentes.supervisor import ESPECIALISTAS

ESPERADOS = {
    EspecialistaIdentificacao: ("identificacao", {"identificacao"}),
    EspecialistaLimites: ("limites", {"limites", "retencoes"}),
    EspecialistaCoberturas: ("coberturas", {"coberturas"}),
    EspecialistaExtensoes: ("extensoes", {"extensoes"}),
    EspecialistaExclusoes: ("exclusoes", {"exclusoes"}),
    EspecialistaCondicoes: ("condicoes", {"condicoes"}),
}


def _fato(categoria: str, label: str, status: str = "present") -> dict:
    return {"category": categoria, "label": label, "status": status, "evidence": "texto"}


def test_cada_especialidade_tem_sua_classe_individual():
    assert set(CLASSES_ESPECIALISTAS) == set(ESPERADOS)
    for classe, (nome, categorias) in ESPERADOS.items():
        assert classe.nome == nome
        assert classe.categorias == frozenset(categorias)
        assert classe.foco


def test_especialistas_sao_classes_distintas_e_nomeadas():
    assert len({classe.__name__ for classe in CLASSES_ESPECIALISTAS}) == 6
    assert all(issubclass(classe, EspecialistaNode) for classe in CLASSES_ESPECIALISTAS)


def test_supervisor_plano_usa_os_mesmos_nomes():
    assert set(ESPECIALISTAS) == {nome for nome, _ in ESPERADOS.values()}


def test_criar_especialistas_devolve_uma_instancia_por_classe():
    nos = criar_especialistas()
    assert set(nos) == set(ESPECIALISTAS)
    for nome, node in nos.items():
        assert isinstance(node, EspecialistaNode)
        assert node.nome == nome


def test_especialista_analisa_somente_a_sua_fasia():
    nos = criar_especialistas()
    estado = {
        "fatos": [
            _fato("identificacao", "Seguradora"),
            _fato("limites", "Limite máximo de responsabilidade"),
            _fato("coberturas", "Cobertura A — indenização ao segurado"),
        ]
    }
    achado_limites = nos["limites"](estado)["achados"][0]
    assert achado_limites["especialista"] == "limites"
    assert achado_limites["categorias"] == ["limites", "retencoes"]
    assert "Limite máximo" not in achado_limites["veredito"] or "1/1" in achado_limites["veredito"]
    assert "Cobertura A" not in achado_limites["veredito"]


def test_especialista_emite_lacunas_no_veredito():
    nos = criar_especialistas()
    estado = {"fatos": [_fato("coberturas", "Cobertura B — reembolso à sociedade", status="not_found")]}
    achado = nos["coberturas"](estado)["achados"][0]
    assert "0/1" in achado["veredito"]
    assert "Cobertura B" in achado["veredito"]


def test_classe_incompleta_e_rejeitada():
    class EspecialistaQuebrado(EspecialistaNode):
        nome = "quebrado"

    try:
        EspecialistaQuebrado()
        raise AssertionError("deveria exigir categorias e foco")
    except ValueError as exc:
        assert "categorias" in str(exc)


class ClienteCaptura:
    """Stub de cliente LLM que grava o prompt recebido e devolve veredito."""

    def __init__(self) -> None:
        self.mensagens: list | None = None

    def chat_json(self, mensagens: list) -> dict:
        self.mensagens = mensagens
        return {"veredito": "ok"}


def test_especialista_recebe_instrucao_no_estado_e_no_prompt():
    cliente = ClienteCaptura()
    nos = criar_especialistas(cliente=cliente)
    estado = {
        "fatos": [_fato("limites", "Limite máximo de responsabilidade")],
        "instrucoes": {"limites": "foco no limite agregado"},
        "pedido_usuario": "compare tudo",
    }
    achado = nos["limites"](estado)["achados"][0]
    assert achado["instrucao"] == "foco no limite agregado"
    assert achado["ferramentas"] == []
    system, usuario = cliente.mensagens
    assert system["content"] == nos["limites"].prompt_sistema
    assert "foco no limite agregado" in usuario["content"]


def test_especialista_sem_instrucao_usa_o_pedido_do_usuario():
    nos = criar_especialistas()
    estado = {"fatos": [_fato("limites", "Franquia")], "pedido_usuario": "compare os limites"}
    achado = nos["limites"](estado)["achados"][0]
    assert achado["instrucao"] == "compare os limites"


def test_contrato_dos_especialistas_na_propriedade():
    nos = criar_especialistas()
    for nome, node in nos.items():
        assert node.contrato.nome == f"especialista_{nome}"
        assert node.contrato.ferramentas == frozenset()
        assert node.contrato.prompt_sistema == node.prompt_sistema
        assert node.foco in node.contrato.papel


def test_especialista_injeta_memoria_no_prompt():
    cliente = ClienteCaptura()
    nos = criar_especialistas(cliente=cliente)
    estado = {
        "fatos": [_fato("limites", "Limite máximo de responsabilidade")],
        "instrucoes": {"limites": "foco no limite"},
        "pedido_usuario": "compare",
        "memoria_contexto": ["análise anterior: limite divergiu entre as apólices"],
    }
    nos["limites"](estado)
    system, usuario = cliente.mensagens
    assert system["content"] == nos["limites"].prompt_sistema
    assert "Análises anteriores" in usuario["content"]
    assert "limite divergiu" in usuario["content"]
    assert "foco no limite" in usuario["content"]


def test_especialista_recebe_trechos_recuperados_com_pagina_no_prompt():
    class MemoriaComTrechos:
        def __init__(self) -> None:
            self.consulta = None

        def recuperar_trechos(self, pergunta: str, document_ids: list[str], k: int = 2) -> list[dict]:
            self.consulta = (pergunta, document_ids, k)
            return [
                {
                    "document_id": "doc-a",
                    "document_name": "Apólice A",
                    "page_number": 2,
                    "extraction_method": "pdf-text",
                    "text": "Limite máximo de R$ 10 milhões.",
                },
                {
                    "document_id": "doc-b",
                    "document_name": "Apólice B",
                    "page_number": 4,
                    "extraction_method": "ocr",
                    "text": "Limite máximo de R$ 15 milhões.",
                },
            ]

    cliente = ClienteCaptura()
    memoria = MemoriaComTrechos()
    node = EspecialistaLimites(cliente=cliente, memoria=memoria)
    estado = {
        "documentos": [
            {"document_id": "doc-a", "name": "Apólice A"},
            {"document_id": "doc-b", "name": "Apólice B"},
        ],
        "fatos": [],
        "pedido_usuario": "compare os limites",
    }

    achado = node(estado)["achados"][0]
    _, usuario = cliente.mensagens

    assert memoria.consulta[1] == ["doc-a", "doc-b"]
    assert [trecho["page_number"] for trecho in achado["trechos_documentais"]] == [2, 4]
    assert "Apólice A" in usuario["content"]
    assert "R$ 10 milhões" in usuario["content"]
    assert "R$ 15 milhões" in usuario["content"]
    assert "cite nome do documento e página" in usuario["content"]


def test_especialista_sem_memoria_nao_monta_o_bloco():
    cliente = ClienteCaptura()
    nos = criar_especialistas(cliente=cliente)
    estado = {"fatos": [_fato("limites", "Franquia")], "pedido_usuario": "compare"}
    nos["limites"](estado)
    _, usuario = cliente.mensagens
    assert "Análises anteriores" not in usuario["content"]
