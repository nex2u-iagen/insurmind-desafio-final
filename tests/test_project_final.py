from pathlib import Path

import pytest

from seguramente_final.ingest import IngestionError, extract_pdf_pages, load_document
from seguramente_final.pipeline import analyze_policies
from seguramente_final.storage import PolicyStore
from seguramente_final.telemetria import eventos_da_thread, limpar_eventos, rodar_com_contexto

ROOT = Path(__file__).resolve().parents[1]
POLICY_A = ROOT / "data" / "policies" / "Apolice_DO_A.pdf"
POLICY_B = ROOT / "data" / "policies" / "Apolice_DO_B.pdf"


class _MotorOcrFalso:
    """Motor OCR injetável: registra páginas e devolve texto sintético."""

    def __init__(self) -> None:
        self.paginas: list[int] = []

    def reconhecer_pagina_pdf(self, path: object, page_number: int) -> str:
        self.paginas.append(page_number)
        return f"ocr simulado {page_number}"


def test_extract_pdf_pages_com_forcar_ocr_aciona_motor_e_mantem_texto_nativo():
    motor = _MotorOcrFalso()
    limpar_eventos("t-forcar-ocr")
    paginas = rodar_com_contexto("t-forcar-ocr", lambda: extract_pdf_pages(POLICY_A, ocr=motor, forcar_ocr=True))
    assert motor.paginas == [1, 2, 3]  # simulação executa OCR em toda página
    etapas = [evento["etapa"] for evento in eventos_da_thread("t-forcar-ocr")]
    assert "tool:extrair_texto_ocr" in etapas  # card do OCR acende no painel
    assert all(pagina.extraction_method == "pdf-text" for pagina in paginas)
    assert all(not pagina.text.startswith("ocr simulado") for pagina in paginas)  # nativo preservado


def test_extract_pdf_pages_sem_forcar_ocr_nao_aciona_motor_no_corpus_textual():
    motor = _MotorOcrFalso()
    limpar_eventos("t-natural-ocr")
    paginas = rodar_com_contexto("t-natural-ocr", lambda: extract_pdf_pages(POLICY_A, ocr=motor))
    assert motor.paginas == []
    etapas = [evento["etapa"] for evento in eventos_da_thread("t-natural-ocr")]
    assert "tool:extrair_texto_ocr" not in etapas
    assert all(pagina.extraction_method == "pdf-text" for pagina in paginas)


def test_ingestao_pdf_preserva_paginas_e_texto():
    document = load_document(POLICY_A, name="A")
    assert document.document_id
    assert len(document.pages) == 3
    assert any("LIMITE MÁXIMO DE RESPONSABILIDADE" in page.text for page in document.pages)
    assert all(page.extraction_method.startswith("pdf") or page.extraction_method == "ocr" for page in document.pages)


def test_pipeline_offline_extrai_e_compara_duas_apolices(tmp_path):
    result = analyze_policies([POLICY_A, POLICY_B], provider_mode="offline", store_path=tmp_path / "policies.db")
    assert len(result.documents) == 2
    assert len(result.comparison) >= 10
    limits = [row for row in result.comparison if row.label == "Limite máximo de responsabilidade"]
    assert limits[0].status == "diferente"
    assert "10.000.000" in (limits[0].policy_a or "")
    assert "15.000.000" in (limits[0].policy_b or "")
    assert limits[0].page_a is not None
    assert limits[0].page_b is not None


def test_storage_registra_documentos_paginas_fatos_e_comparacoes(tmp_path):
    db = tmp_path / "policies.db"
    result = analyze_policies([POLICY_A, POLICY_B], provider_mode="offline", store_path=db)
    counts = PolicyStore(db).counts()
    assert counts["documents"] == 2
    assert counts["pages"] == 6
    assert counts["facts"] >= 30
    assert counts["comparisons"] == len(result.comparison)


def test_comparacao_explicita_diferenca_evidencia():
    result = analyze_policies(
        [POLICY_A, POLICY_B], provider_mode="offline", store_path=ROOT / "data" / "test_policies.db"
    )
    row = next(item for item in result.comparison if item.label == "Período adicional de notificação")
    assert row.status == "diferente"
    assert row.evidence_a
    assert row.evidence_b


def test_pipeline_exige_duas_apolices(tmp_path):
    with pytest.raises(ValueError):
        analyze_policies([POLICY_A], provider_mode="offline", store_path=tmp_path / "policies.db")


def test_formato_invalido_e_rejeitado(tmp_path):
    invalid = tmp_path / "documento.txt"
    invalid.write_text("texto")
    with pytest.raises(IngestionError):
        load_document(invalid)


class _ExtratorComFallback:
    """Extrator LLM simulado que já caiu para as regras offline."""

    name = "llm"
    model = "modelo-teste"
    fallback_aplicado = True

    def extract(self, document):
        from seguramente_final.rules import RuleBasedExtractor

        return RuleBasedExtractor().extract(document)


def test_pipeline_reporta_fallback_offline_no_resultado(tmp_path):
    result = analyze_policies(
        [POLICY_A, POLICY_B],
        provider_mode="offline",
        store_path=tmp_path / "policies.db",
        extractor=_ExtratorComFallback(),
    )
    assert result.fallback_offline is True
    assert result.to_dict()["fallback_offline"] is True


def test_pipeline_offline_sem_fallback_sai_false(tmp_path):
    result = analyze_policies([POLICY_A, POLICY_B], provider_mode="offline", store_path=tmp_path / "p.db")
    assert result.fallback_offline is False
    assert result.to_dict()["fallback_offline"] is False


class _ClienteSemLLM:
    """Cliente que sempre falha (LLMError) para exercitar o fallback do resumo."""

    model = "modelo-teste"

    def chat_json(self, messages, **kwargs):
        from seguramente_final.motor_llm import LLMError

        raise LLMError("indisponível")


class _ExtratorComClienteQuebrado(_ExtratorComFallback):
    """Extrator com cliente LLM quebrado: extração offline + resumo offline."""

    fallback_aplicado = False
    cliente = _ClienteSemLLM()

    def extract(self, document):
        from seguramente_final.rules import RuleBasedExtractor

        return RuleBasedExtractor().extract(document)


def test_pipeline_resumo_llm_falho_cai_para_offline_e_marca_fallback(tmp_path):
    result = analyze_policies(
        [POLICY_A, POLICY_B],
        provider_mode="google",
        store_path=tmp_path / "policies.db",
        extractor=_ExtratorComClienteQuebrado(),
    )
    assert result.executive_summary
    assert result.fallback_offline is True
