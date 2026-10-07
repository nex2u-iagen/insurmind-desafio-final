"""Teste de fluxo completo do front — pedido → gate → decisão → fim (AppTest)."""

from __future__ import annotations

import time
from pathlib import Path

from streamlit.testing.v1 import AppTest

from seguramente_final.telemetria import eventos_da_thread

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
ACOES_GATE = ["aprovado", "aprovado com ressalvas", "reprovado", "solicitar ajuste"]
PEDIDO = "Compare os limites e as coberturas das duas apólices"


def _chat(at: AppTest) -> str:
    return "\n".join(str(m.get("content")) for m in at.session_state["chat"])


def _esperar(at: AppTest, modo: str, tentativas: int = 90) -> None:
    """Roda o app até o modo esperado (worker offline + OCR pode levar)."""
    for _ in range(tentativas):
        at.run()
        assert not at.exception
        if at.session_state["modo"] == modo:
            return
        time.sleep(0.5)
    raise AssertionError(f"esperava modo {modo!r}; obtido {at.session_state['modo']!r}")


def test_fluxo_completo_pedido_gate_decisao_fim():
    at = AppTest.from_file(str(APP), default_timeout=180).run()
    assert not at.exception
    assert at.session_state["modo"] == "ocioso"

    at.chat_input[0].set_value(PEDIDO).run()
    _esperar(at, "gate")
    assert "Gate humano acionado" in _chat(at)

    estado = at.session_state["resultado"].estado
    assert "limites" in estado["plano"]  # roteamento por keywords do pedido
    assert any(a["especialista"] == "limites" for a in estado["achados"])

    indice = next(i for i, sb in enumerate(at.selectbox) if list(sb.options) == ACOES_GATE)
    at.selectbox[indice].set_value("aprovado").run()
    comentario = next(ta for ta in at.text_area if "Comentário" in str(ta.label))
    comentario.set_value("sem ressalvas").run()
    botao = next(b for b in at.button if "Enviar decisão" in str(b.label))
    botao.click().run()
    _esperar(at, "fim")

    assert not at.exception
    assert "aprovado" in _chat(at)
    assert "documentos" in _chat(at)
    assert at.session_state["resultado"].estado["plano"] == ["limites", "coberturas"]

    eventos = eventos_da_thread(at.session_state["thread_id"])
    assert eventos and eventos[-1]["status"] == "ok"
