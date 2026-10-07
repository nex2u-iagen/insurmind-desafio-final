"""Testes TDD do front da orquestra — pills de quadrante e cartão de detalhe."""

from __future__ import annotations

import re
from pathlib import Path

from streamlit.testing.v1 import AppTest

from seguramente_final.agentes.orquestrador import ResultadoAnalise

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


def _app() -> AppTest:
    return AppTest.from_file(str(APP), default_timeout=30)


def _texto(at: AppTest) -> str:
    """Concatena markdown, código e legendas renderizados (asserções de detalhe)."""
    partes = [str(m.value) for m in at.markdown]
    partes += [str(c.value) for c in getattr(at, "code", [])]
    partes += [str(c.value) for c in getattr(at, "caption", [])]
    return "\n".join(partes)


def _sem_emoji(texto: str) -> str:
    """O AppTest reporta as options sem emoji (o valor do widget mantém)."""
    return re.sub(r"[^\w\s]", "", texto).strip()


def _legenda_status(at: AppTest) -> list[str]:
    """Legendas ``Status: ...`` do cartão de detalhe (exclui a legenda do painel)."""
    return [str(c.value) for c in at.caption if str(c.value).startswith("Status:")]


def _resultado_falso() -> ResultadoAnalise:
    """Resultado já finalizado com plano restrito (plano=['limites'])."""
    return ResultadoAnalise(
        thread_id="thread-front",
        interrompido=True,
        pontos=[],
        mensagem="Supervisor: análise concluída.",
        estado={
            "plano": ["limites"],
            "pedido_usuario": "compare os limites",
            "instrucoes": {"limites": "compare os limites"},
            "achados": [
                {
                    "especialista": "limites",
                    "veredito": "limites: 2/2 campos presentes",
                    "instrucao": "compare os limites",
                    "ferramentas": [],
                }
            ],
        },
    )


def test_app_renderiza_sem_excecao_e_mostra_detalhe_padrao():
    at = _app().run()
    assert not at.exception
    assert any("Orquestra" in str(s.value) for s in at.subheader)
    texto = _texto(at)
    assert "🤖 agente" in texto  # detalhe padrão: Supervisor (tipo + status)
    assert "Papel" not in texto


def test_pills_expoe_todos_os_quadrantes():
    at = _app().run()
    assert at.pills
    opcoes = [_sem_emoji(str(o)) for o in at.pills[0].options]
    assert len(opcoes) == 18  # 2 maestro + 12 agentes + 4 tools
    for esperado in ("Supervisor", "Ingestor", "Comparador", "Limites", "ingestar_documentos"):
        assert esperado in opcoes


def test_detalhe_mostra_somente_tipo_e_status():
    at = _app().run()
    at.pills[0].set_value("Comparador").run()
    assert not at.exception
    texto = _texto(at)
    assert "🤖 agente" in texto  # legenda do ícone do tipo
    assert _legenda_status(at)  # status presente
    for ausente in ("Papel", "@comparar_apolices", "evidência", "Input", "Output"):
        assert ausente not in texto  # detalhe limitado às legendas dos ícones


def test_detalhe_do_sintetizador_mostra_tipo_sem_prompt():
    at = _app().run()
    at.pills[0].set_value("Sintetizador").run()
    texto = _texto(at)
    assert "🤖 agente" in texto
    assert "@resumir_comparacao" not in texto


def test_detalhe_da_tool_mostra_legenda_de_ferramenta():
    at = _app().run()
    at.pills[0].set_value("ingestar_documentos").run()
    texto = _texto(at)
    assert "🔨 ferramenta" in texto
    assert "Ingesta apólices" not in texto  # descrição do registry não aparece mais


def test_cartoes_exibem_badge_de_quantidade_de_tools():
    at = _app().run()
    html = "\n".join(str(m.value) for m in at.markdown)
    assert "⚡2" in html  # Ingestor: ingestar_documentos + extrair_texto_ocr
    assert "⚡1" in html  # Extrator, Comparador e Sintetizador


def test_detalhe_do_especialista_mostra_tipo_e_status():
    at = _app().run()
    at.session_state["resultado"] = _resultado_falso()
    at.run()
    at.pills[0].set_value("Limites").run()
    texto = _texto(at)
    assert not at.exception
    assert "🤖 agente" in texto
    assert "**Input:**" not in texto  # input/output não aparecem mais no detalhe
    assert "2/2 campos presentes" not in texto


def test_especialista_fora_do_plano_aparece_marcado_no_detalhe():
    at = _app().run()
    at.session_state["resultado"] = _resultado_falso()
    at.run()
    at.pills[0].set_value("Coberturas").run()
    assert "Status: fora do plano" in _legenda_status(at)
    at.pills[0].set_value("Limites").run()
    assert not any("fora do plano" in legenda for legenda in _legenda_status(at))


def test_orquestra_desenha_as_arestas_do_grafo():
    at = _app().run()
    assert not at.exception
    html = "\n".join(str(m.value) for m in at.markdown)
    assert "<svg" in html
    assert html.count("<line") == 24  # 19 arestas do fluxo + 5 ramos de ferramenta
    assert html.count("marker-end=") == 19  # setas no caminho principal
    assert html.count('x1="72" y1="303"') == 7  # fan-out do Extrator (6) + ramo até a tool de OCR
    assert html.count('stroke-dasharray="4 5"') == 5  # ramos pontilhados até as tools
    assert "caminho" in html  # legenda das linhas


def test_cartoes_usam_icone_de_agente_e_de_ferramenta():
    at = _app().run()
    assert not at.exception
    html = next(str(m.value) for m in at.markdown if "<svg" in str(m.value))
    assert html.count("\U0001f916") == 14  # 2 do maestro + 12 agentes da fila
    assert html.count("\U0001f528") == 4  # fila de tools


def test_sidebar_persiste_chave_e_modelo_no_env(tmp_path, monkeypatch):
    from dotenv import dotenv_values

    alvo = tmp_path / ".env"
    monkeypatch.setenv("SEGURAMENTE_ENV_FILE", str(alvo))

    at = _app().run()
    assert not at.exception
    provedor = next(s for s in at.selectbox if str(s.label) == "Provedor")
    provedor.set_value("openai").run()
    modelo = next(t for t in at.text_input if str(t.label) == "Modelo")
    modelo.set_value("gpt-teste").run()
    chave = next(t for t in at.text_input if str(t.label) == "API key")
    chave.set_value("sk-teste-123").run()

    assert not at.exception
    valores = dotenv_values(alvo)
    assert valores["OPENAI_API_KEY"] == "sk-teste-123"
    assert valores["OPENAI_MODEL"] == "gpt-teste"


def test_botao_salvar_env_grava_e_mostra_sucesso(tmp_path, monkeypatch):
    from dotenv import dotenv_values

    alvo = tmp_path / ".env"
    monkeypatch.setenv("SEGURAMENTE_ENV_FILE", str(alvo))

    at = _app().run()
    provedor = next(s for s in at.selectbox if str(s.label) == "Provedor")
    provedor.set_value("groq").run()
    modelo = next(t for t in at.text_input if str(t.label) == "Modelo")
    modelo.set_value("llama-teste").run()
    chave = next(t for t in at.text_input if str(t.label) == "API key")
    chave.set_value("gsk-123").run()

    assert not at.exception
    assert not at.success  # sem feedback visível antes do clique

    alvo.write_text("")  # prova que o clique (re)grava o arquivo
    botao = next(b for b in at.button if "Salvar" in str(b.label))
    botao.click().run()

    assert not at.exception
    assert any("gravad" in str(s.value).lower() for s in at.success)
    valores = dotenv_values(alvo)
    assert valores["GROQ_API_KEY"] == "gsk-123"
    assert valores["GROQ_MODEL"] == "llama-teste"


def test_sidebar_status_do_env_nao_expoe_a_chave(tmp_path, monkeypatch):
    alvo = tmp_path / ".env"
    monkeypatch.setenv("SEGURAMENTE_ENV_FILE", str(alvo))

    at = _app().run()
    provedor = next(s for s in at.selectbox if str(s.label) == "Provedor")
    provedor.set_value("groq").run()
    chave = next(t for t in at.text_input if str(t.label) == "API key")
    chave.set_value("gsk-super-secreta-999").run()

    assert not at.exception
    legendas = "\n".join(str(c.value) for c in at.caption)
    assert "gsk-super-secreta-999" not in legendas
    assert "presente" in legendas


def test_sidebar_tem_checkbox_de_simulacao_de_ocr():
    at = _app().run()
    assert not at.exception
    rotulos = [str(c.label) for c in at.checkbox]
    assert any("OCR" in rotulo for rotulo in rotulos)


def test_aviso_degradacao_lista_motivos_e_fica_vazio():
    """O front precisa dizer quando a análise rodou offline (senão parece sucesso)."""
    import app

    assert app._aviso_degradacao({}) == ""
    aviso = app._aviso_degradacao({"fallback_extrator": True, "fallback_resumo": True})
    assert "Modo degradado" in aviso
    assert "extração por LLM" in aviso
    assert "resumo por LLM" in aviso
    assert "Modo degradado" not in app._aviso_degradacao({"fallback_extrator": False})
    aviso_epoch = app._aviso_degradacao({"indexacao_documental": {"available": False}})
    assert "epochDB indisponível" in aviso_epoch


def test_aviso_degradacao_inclui_motivo_acionavel_sem_url():
    import app

    estado = {
        "fallback_extrator": True,
        "fallback_resumo": True,
        "motivo_degradacao": (
            "Falha na chamada ao modelo gemini-3.7-flash: 429 Client Error: Too Many Requests "
            "for url: https://generativelanguage.googleapis.com/v1beta/...?key=*** — "
            "cota gratuita do Google esgotada; nova tentativa em ~10h49m (troque GOOGLE_MODEL ou aguarde)"
        ),
    }
    aviso = app._aviso_degradacao(estado)
    assert "_Motivo:_" in aviso
    assert "cota gratuita do Google esgotada" in aviso
    assert "generativelanguage.googleapis.com" not in aviso  # URL some; só o trecho acionável fica


def test_app_nao_usa_fragment_com_run_every():
    """Guarda de regressão: @st.fragment(run_every=...) + rerun do HITL dava tela branca.

    O fragment auto-rerunava a cada 0.4s e, ao consumir o desfecho da worker,
    chamava ``st.rerun()`` (escopo app) de dentro dele; o frontend recebia deltas
    em caminhos órfãos e crashava com "Cannot set a node at a delta path".
    O polling passou a viver no script principal (fonte única de rerun).
    """
    import ast

    arvore = ast.parse(APP.read_text(encoding="utf-8"))
    fragmentos = [
        no
        for no in ast.walk(arvore)
        if isinstance(no, ast.Call)
        and isinstance(no.func, ast.Attribute)
        and no.func.attr in {"fragment", "fragment_run_every"}
    ]
    assert fragmentos == [], f"@st.fragment reintroduzido em {APP}"


def test_app_pausa_polling_quando_worker_nao_retorna():
    """Limite de15 min: sem desfecho, a interface encerra em vez de rerun infinito."""
    import time as tempo

    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=60).run()
    at.session_state["modo"] = "rodando"
    at.session_state["inicio_rodando"] = tempo.time() - 1000
    at.run()
    assert not at.exception
    assert at.session_state["modo"] == "fim"
    assert any("não retornou" in str(m.get("content")) for m in at.session_state["chat"])
