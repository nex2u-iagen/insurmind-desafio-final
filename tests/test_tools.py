"""Testes TDD do registry de ferramentas e das tools de documento."""

from __future__ import annotations

from pathlib import Path

from seguramente_final.tools import comparar_apolices, ingestar_documentos, listar_ferramentas, resumir_comparacao

ROOT = Path(__file__).resolve().parents[1]
POLICY_A = ROOT / "data" / "policies" / "Apolice_DO_A.pdf"
POLICY_B = ROOT / "data" / "policies" / "Apolice_DO_B.pdf"


def test_registry_expoe_allowlist():
    assert set(listar_ferramentas()) == {
        "ingestar_documentos",
        "comparar_apolices",
        "resumir_comparacao",
        "extrair_texto_ocr",
    }


def test_extrair_texto_ocr_e_melhor_esforco_sem_excecao():
    from seguramente_final.tools import extrair_texto_ocr

    assert extrair_texto_ocr("/caminho/inexistente/imagem.png") == ""


def test_ingestar_documentos_retorna_dicts_json_safe():
    import json

    docs = ingestar_documentos([str(POLICY_A), str(POLICY_B)], nomes=["Apólice A", "Apólice B"])
    assert len(docs) == 2
    assert docs[0]["name"] == "Apólice A"
    assert len(docs[0]["pages"]) == 3
    json.dumps(docs)


def test_ingestar_documentos_repassa_forcar_ocr_para_load_document(monkeypatch):
    from seguramente_final.models import PolicyDocument
    from seguramente_final.tools import documento as modulo_documento

    capturas: list[dict] = []

    def _load_falso(path, name=None, **kwargs):
        capturas.append({"path": str(path), "name": name, **kwargs})
        return PolicyDocument(document_id="FAKE", name=name or "doc", path=str(path), source="teste", pages=[])

    monkeypatch.setattr(modulo_documento, "load_document", _load_falso)
    docs = ingestar_documentos([str(POLICY_A)], nomes=["A"], forcar_ocr=True)
    assert capturas[0]["forcar_ocr"] is True
    assert capturas[0]["name"] == "A"
    assert docs[0]["document_id"] == "FAKE"


def test_comparar_apolices_retorna_19_linhas_com_evidencia():
    linhas = comparar_apolices(str(POLICY_A), str(POLICY_B))
    assert len(linhas) == 19
    limite = next(row for row in linhas if row["label"] == "Limite máximo de responsabilidade")
    assert limite["status"] == "diferente"
    assert limite["evidence_a"] and limite["evidence_b"]
    assert limite["page_a"] is not None


def test_resumir_comparacao_offline_conta_diferencas():
    linhas = comparar_apolices(str(POLICY_A), str(POLICY_B))
    resumo = resumir_comparacao(linhas)
    assert "diferenças" in resumo or "lacunas" in resumo
    assert "parecer jurídico" in resumo


def test_extrator_llm_monta_user_prompt_sem_keyerror_nas_chaves_json():
    """O exemplo JSON do prompt tem chaves literais — não pode quebrar o .format()."""
    from types import SimpleNamespace

    from seguramente_final.rules import normalizar_valor
    from seguramente_final.tools.extrator import ExtratorLLM

    class ClienteFake:
        model = "fake"

        def chat_json(self, messages, **kwargs):
            self.messages = messages
            return {
                "facts": [
                    {
                        "label": "Limite máximo de responsabilidade",
                        "category": "limites",
                        "value": "R$ 10.000.000,00",
                        "evidence": "Limite máximo: R$ 10.000.000,00",
                        "page": 3,
                    },
                    {"name": "Franquia / retenção", "value": "R$ 50.000,00", "page": 4},
                ]
            }

    cliente = ClienteFake()
    doc = SimpleNamespace(document_id="doc-a", source="Apolice_DO_A.pdf", pages=[])
    fatos = ExtratorLLM(cliente).extract(doc)

    user = cliente.messages[1]["content"]
    assert str(doc) in user  # texto do documento injetado no prompt
    assert '{"facts":' in user  # exemplo JSON literal chega intacto
    assert "Limite máximo de responsabilidade" in user  # rótulos canônicos do schema no prompt

    assert len(fatos) == 19
    fatos_por_rotulo = {f.label: f for f in fatos}
    limite = fatos_por_rotulo["Limite máximo de responsabilidade"]
    franquia = fatos_por_rotulo["Franquia / retenção"]
    assert (limite.document_id, limite.category, limite.status, limite.source) == (
        "doc-a",
        "limites",
        "present",
        "Apolice_DO_A.pdf",
    )
    assert limite.normalized_value == normalizar_valor("R$ 10.000.000,00")
    assert franquia.category == "retencoes"  # categoria canônica via rótulo do schema


def test_extrator_llm_aceita_dict_serializado_como_as_demais_tools():
    """O estado do grafo carrega dicts; o extrator precisa aceitar o mesmo contrato."""
    from seguramente_final.tools.extrator import ExtratorLLM

    class ClienteFake:
        model = "fake"

        def chat_json(self, messages, **kwargs):
            return {
                "facts": [
                    {
                        "label": "Limite máximo de responsabilidade",
                        "category": "limites",
                        "value": "R$ 10.000.000,00",
                        "evidence": "LIMITE MÁXIMO: R$ 10.000.000,00",
                        "page": 2,
                    }
                ]
            }

    docs = ingestar_documentos([str(POLICY_A)], nomes=["Apólice A"])
    extrator = ExtratorLLM(ClienteFake())
    fatos = extrator.extract(docs[0])
    assert len(fatos) == 19
    assert fatos[0].document_id == docs[0]["document_id"]
    assert extrator.fallback_aplicado is False
    assert extrator.complemento_regras == 18


def test_extrator_llm_aceita_chave_fatos_em_portugues():
    """Alguns modelos devolvem 'fatos'; não pode virar fallback desnecessário."""
    from seguramente_final.tools.extrator import ExtratorLLM

    class ClienteFatos:
        model = "fake"

        def chat_json(self, messages, **kwargs):
            return {
                "fatos": [
                    {
                        "label": "Franquia / retenção",
                        "category": "retencoes",
                        "value": "R$ 50.000,00",
                        "evidence": "FRANQUIA: R$ 50.000,00",
                        "page": 2,
                    }
                ]
            }

    docs = ingestar_documentos([str(POLICY_A)], nomes=["Apólice A"])
    extrator = ExtratorLLM(ClienteFatos())
    fatos = extrator.extract(docs[0])
    assert len(fatos) == 19
    assert next(f for f in fatos if f.label == "Franquia / retenção").value == "R$ 50.000,00"
    assert extrator.fallback_aplicado is False


def test_extrator_llm_completa_campos_omitidos_com_regras(caplog):
    from seguramente_final.models import DocumentPage, PolicyDocument
    from seguramente_final.tools.extrator import ExtratorLLM

    class ClienteParcial:
        model = "fake"

        def chat_json(self, messages, **kwargs):
            return {
                "facts": [
                    {
                        "label": "Seguradora",
                        "value": "Segura S.A.",
                        "evidence": "SEGURADORA: Segura S.A.",
                        "page": 1,
                    }
                ]
            }

    documento = PolicyDocument(
        document_id="doc-parcial",
        name="Parcial",
        path="parcial.pdf",
        source="teste",
        pages=[
            DocumentPage(
                document_id="doc-parcial",
                page_number=1,
                text="SEGURADORA: Segura S.A.\nLIMITE MÁXIMO DE RESPONSABILIDADE: R$ 10.000.000,00",
                extraction_method="pdf-text",
            )
        ],
    )
    extrator = ExtratorLLM(ClienteParcial())

    with caplog.at_level("WARNING", logger="seguramente_final.tools.extrator"):
        fatos = extrator.extract(documento)

    por_rotulo = {fato.label: fato for fato in fatos}
    assert len(fatos) == 19
    assert por_rotulo["Seguradora"].status == "present"
    assert por_rotulo["Limite máximo de responsabilidade"].value == "R$ 10.000.000,00"
    assert por_rotulo["Limite máximo de responsabilidade"].evidence.startswith("LIMITE MÁXIMO")
    assert extrator.fatos_llm == 1
    assert extrator.complemento_regras == 18
    assert extrator.fallback_aplicado is False
    assert "campos_llm=1/19" in caplog.text


def test_extrator_llm_marca_conflito_com_regra_como_ambiguo():
    from seguramente_final.models import DocumentPage, PolicyDocument
    from seguramente_final.tools.extrator import ExtratorLLM

    class ClienteDivergente:
        model = "fake"

        def chat_json(self, messages, **kwargs):
            return {
                "facts": [
                    {
                        "label": "Limite máximo de responsabilidade",
                        "value": "R$ 15.000.000,00",
                        "evidence": "Limite máximo: R$ 15.000.000,00",
                        "page": 1,
                    }
                ]
            }

    documento = PolicyDocument(
        document_id="doc-conflito",
        name="Conflito",
        path="conflito.pdf",
        source="teste",
        pages=[
            DocumentPage(
                document_id="doc-conflito",
                page_number=1,
                text="LIMITE MÁXIMO DE RESPONSABILIDADE: R$ 10.000.000,00",
                extraction_method="pdf-text",
            )
        ],
    )

    extrator = ExtratorLLM(ClienteDivergente())
    fatos = extrator.extract(documento)
    limite = next(fato for fato in fatos if fato.label == "Limite máximo de responsabilidade")

    assert len(fatos) == 19
    assert limite.status == "ambiguous"
    assert "R$ 15.000.000,00" in limite.evidence
    assert "R$ 10.000.000,00" in limite.evidence
    assert extrator.conflitos == 1


def test_resumir_comparacao_com_memoria_injeta_contexto():
    from seguramente_final.tools.resumidor import ResumidorLLM  # noqa: F401 — contrato do cliente

    class ClienteCaptura:
        def chat_json(self, mensagens: list, **kwargs) -> dict:
            self.mensagens = mensagens
            return {"resumo": "resumo ok"}

    linhas = comparar_apolices(str(POLICY_A), str(POLICY_B))
    cliente = ClienteCaptura()
    resumo = resumir_comparacao(linhas, cliente, memoria_contexto=["análise anterior: limite divergiu"])
    assert resumo == "resumo ok"
    usuario = cliente.mensagens[1]["content"]
    assert "Análises anteriores" in usuario
    assert "limite divergiu" in usuario
    assert '"label"' in usuario  # linhas comparadas seguem no prompt


def test_resumir_comparacao_injeta_pedido_e_trechos_dos_especialistas():
    class ClienteCaptura:
        def chat_json(self, mensagens: list, **kwargs) -> dict:
            self.mensagens = mensagens
            return {"resumo": "limites divergentes conforme as evidências"}

    linhas = comparar_apolices(str(POLICY_A), str(POLICY_B))
    cliente = ClienteCaptura()
    achados = [
        {
            "especialista": "limites",
            "veredito": "Diferença entre limites máximos.",
            "veredito_llm": "A apólice B prevê limite maior.",
            "trechos_documentais": [
                {
                    "document_id": "doc-a",
                    "document_name": "Apólice A",
                    "page_number": 2,
                    "text": "Limite máximo de R$ 10 milhões.",
                }
            ],
        }
    ]

    resumir_comparacao(
        linhas,
        cliente,
        achados=achados,
        pedido_usuario="Compare os limites máximos.",
    )

    usuario = cliente.mensagens[1]["content"]
    assert "Pedido do usuário: Compare os limites máximos." in usuario
    assert "Achados dos especialistas" in usuario
    assert "Apólice A" in usuario
    assert "R$ 10 milhões" in usuario


def test_resumir_comparacao_sem_memoria_mantem_prompt_enxuto():
    class ClienteCaptura:
        def chat_json(self, mensagens: list, **kwargs) -> dict:
            self.mensagens = mensagens
            return {"resumo": "resumo ok"}

    linhas = comparar_apolices(str(POLICY_A), str(POLICY_B))
    cliente = ClienteCaptura()
    resumir_comparacao(linhas, cliente)
    assert "Análises anteriores" not in cliente.mensagens[1]["content"]


def test_resumidor_prompt_exige_schema_json_resumo():
    """O modelo deve saber a chave exata; sem schema ele inventa outro formato."""
    from seguramente_final.tools.resumidor import PROMPT_SISTEMA

    assert '{"resumo"' in PROMPT_SISTEMA.replace(" ", "")
    assert "páginas" in PROMPT_SISTEMA


def test_resumidor_prompt_vai_para_system_message():
    from seguramente_final.tools.resumidor import ResumidorLLM

    class ClienteCaptura:
        def chat_json(self, mensagens: list, **kwargs) -> dict:
            self.mensagens = mensagens
            return {"resumo": "ok"}

    cliente = ClienteCaptura()
    linhas = comparar_apolices(str(POLICY_A), str(POLICY_B))
    ResumidorLLM(cliente).summarize(linhas)
    assert cliente.mensagens[0]["role"] == "system"
    assert '{"resumo"' in cliente.mensagens[0]["content"].replace(" ", "")


def test_resumidor_aceita_resposta_string_pura():
    from seguramente_final.tools.resumidor import ResumidorLLM

    class ClienteString:
        def chat_json(self, mensagens: list, **kwargs) -> str:
            return "limite agregado divergiu entre as apólices"

    linhas = comparar_apolices(str(POLICY_A), str(POLICY_B))
    resumo = ResumidorLLM(ClienteString()).summarize(linhas)
    assert resumo == "limite agregado divergiu entre as apólices"


def test_resumidor_resposta_nao_dict_vira_llmerror():
    from seguramente_final.motor_llm.base import LLMError
    from seguramente_final.tools.resumidor import ResumidorLLM

    class ClienteLista:
        def chat_json(self, mensagens: list, **kwargs) -> list:
            return ["não", "é", "objeto"]

    linhas = comparar_apolices(str(POLICY_A), str(POLICY_B))
    try:
        ResumidorLLM(ClienteLista()).summarize(linhas)
        raise AssertionError("deveria levantar LLMError")
    except LLMError as exc:
        assert "vazio" in str(exc)


def test_extrator_llm_registra_motivo_do_fallback_para_o_front():
    """O front precisa mostrar *por que* a análise degradou (cota, 503, ...)."""
    from seguramente_final.ingest import load_document
    from seguramente_final.motor_llm import LLMError
    from seguramente_final.tools.extrator import ExtratorLLM

    class ClienteQuebrado:
        model = "quebrado"

        def chat_json(self, messages, **kwargs):
            raise LLMError("cota gratuita do Google esgotada; nova tentativa em ~10h")

    extrator = ExtratorLLM(ClienteQuebrado())
    fatos = extrator.extract(load_document(POLICY_A))
    assert extrator.fallback_aplicado is True
    assert "cota gratuita" in extrator.motivo_fallback
    assert fatos  # regras offline seguem entregando os campos
