"""Testes TDD do motor LLM — registry de provedores, fábrica e contrato ChatJson."""

from __future__ import annotations

import pytest
import requests

from seguramente_final.motor_llm import LLMError, criar_cliente, provedores_disponiveis
from seguramente_final.motor_llm.base import PROVEDORES


class RespostaFalsa:
    """Adaptador mínimo de ``requests.Response`` para transporte injetável."""

    def __init__(self, payload: dict, status: int = 200, headers: dict | None = None, texto: str = "") -> None:
        self._payload = payload
        self.status_code = status
        self.headers = dict(headers or {})
        self.text = texto

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}", response=self)


class CapturaPost:
    """Substitui ``requests.post``: captura a chamada e devolve resposta pré-programada."""

    def __init__(self, resposta: RespostaFalsa) -> None:
        self.resposta = resposta
        self.chamadas: list[dict] = []

    def __call__(
        self, url: str, headers: dict | None = None, json: dict | None = None, timeout: int | None = None, **kwargs
    ) -> RespostaFalsa:
        self.chamadas.append({"url": url, "headers": headers or {}, "json": json or {}, "timeout": timeout})
        return self.resposta

    @property
    def ultima(self) -> dict:
        return self.chamadas[-1]


def _resposta_openai(content: dict) -> RespostaFalsa:
    return RespostaFalsa({"choices": [{"message": {"content": __import__("json").dumps(content)}}]})


# ---------------------------------------------------------------- registry ---


def test_registry_expoe_tres_provedores():
    assert set(provedores_disponiveis()) == {"openai", "groq", "google"}
    assert set(PROVEDORES) == {"openai", "groq", "google"}


def test_criar_cliente_resolve_provedor_com_defaults():
    cliente = criar_cliente("groq", api_key="g-test", post=lambda *a, **k: None)
    assert type(cliente).__name__ == "ProvedorGroq"
    assert cliente.model == "llama-3.3-70b-versatile"
    assert cliente.base_url.startswith("https://api.groq.com")


def test_criar_cliente_parametros_sobrepoe_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    cliente = criar_cliente("openai", model="gpt-4o-mini", api_key="sk-front")
    assert cliente.api_key == "sk-front"
    assert cliente.model == "gpt-4o-mini"


def test_criar_cliente_usa_env_quando_sem_parametro(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    cliente = criar_cliente("openai")
    assert cliente.api_key == "sk-env"


def test_criar_cliente_provedor_desconhecido_erro():
    try:
        criar_cliente("anthropic")
        raise AssertionError("deveria levantar LLMError")
    except LLMError:
        pass


# --------------------------------------------------------------- openai/groq ---


def test_openai_chat_json_envia_payload_esperado():
    captura = CapturaPost(_resposta_openai({"ok": True}))
    cliente = criar_cliente("openai", model="gpt-4o-mini", api_key="sk-x", post=captura)
    resultado = cliente.chat_json([{"role": "user", "content": "oi"}])
    assert resultado == {"ok": True}
    chamada = captura.ultima
    assert chamada["url"] == "https://api.openai.com/v1/chat/completions"
    assert chamada["headers"]["Authorization"] == "Bearer sk-x"
    assert chamada["json"]["model"] == "gpt-4o-mini"
    assert chamada["json"]["response_format"] == {"type": "json_object"}
    assert chamada["json"]["max_tokens"] == 4096


def test_openai_gpt5_usa_max_completion_tokens():
    captura = CapturaPost(_resposta_openai({"ok": True}))
    cliente = criar_cliente("openai", model="gpt-5-mini", api_key="sk-x", post=captura)
    cliente.chat_json([{"role": "user", "content": "oi"}])
    assert "max_completion_tokens" in captura.ultima["json"]
    assert "max_tokens" not in captura.ultima["json"]


def test_groq_aponta_para_base_url_da_groq():
    captura = CapturaPost(_resposta_openai({"ok": True}))
    cliente = criar_cliente("groq", model="llama-3.3-70b-versatile", api_key="gsk-x", post=captura)
    cliente.chat_json([{"role": "user", "content": "oi"}])
    assert captura.ultima["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert captura.ultima["headers"]["Authorization"] == "Bearer gsk-x"


# ------------------------------------------------------------------ google ---


def test_google_chat_json_parseia_candidates():
    texto = '{"summary": "diferencas"}'
    payload = {"candidates": [{"content": {"parts": [{"text": texto}]}}]}
    captura = CapturaPost(RespostaFalsa(payload))
    cliente = criar_cliente("google", model="gemini-2.0-flash", api_key="g-chave", post=captura)
    resultado = cliente.chat_json([{"role": "user", "content": "oi"}])
    assert resultado == {"summary": "diferencas"}
    url = captura.ultima["url"]
    assert "generativelanguage.googleapis.com" in url
    assert "models/gemini-2.0-flash:generateContent" in url
    assert "key=g-chave" in url


def test_google_resposta_sem_candidates_vira_llmerror():
    captura = CapturaPost(RespostaFalsa({"promptFeedback": {"blockReason": "SAFETY"}}))
    cliente = criar_cliente("google", model="gemini-2.0-flash", api_key="g-chave", post=captura)
    try:
        cliente.chat_json([{"role": "user", "content": "oi"}])
        raise AssertionError("deveria levantar LLMError")
    except LLMError as exc:
        assert "candidat" in str(exc).lower() or "candidates" in str(exc).lower()


# ------------------------------------------------------------------ erros ---


def test_sem_api_key_levanta_llmerror(monkeypatch):
    for var in ("OPENAI_API_KEY", "GROQ_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    cliente = criar_cliente("openai", api_key="")
    try:
        cliente.chat_json([{"role": "user", "content": "oi"}])
        raise AssertionError("deveria levantar LLMError")
    except LLMError as exc:
        assert "OPENAI_API_KEY" in str(exc)


def test_erro_http_vira_llmerror_sem_vazar_chave(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda segundos: None)
    captura = CapturaPost(RespostaFalsa({"erro": True}, status=500))
    cliente = criar_cliente("groq", api_key="gsk-secreta", post=captura)
    try:
        cliente.chat_json([{"role": "user", "content": "oi"}])
        raise AssertionError("deveria levantar LLMError")
    except LLMError as exc:
        assert "gsk-secreta" not in str(exc)


def test_google_nao_vaza_api_key_no_erro(caplog, monkeypatch):
    """A key vai na URL; exceções/log/traceback não podem propagá-la."""
    import logging
    import traceback

    monkeypatch.setattr("time.sleep", lambda segundos: None)
    chave = "AIzaFAKE-SECRET-KEY-123"

    def post_falha(url, **kwargs):
        raise requests.ConnectionError(f"connection error for url: {url}")

    cliente = criar_cliente("google", api_key=chave, post=post_falha)
    with caplog.at_level(logging.WARNING, logger="seguramente_final.motor_llm.google"):
        try:
            cliente.chat_json([{"role": "user", "content": "oi"}])
            raise AssertionError("deveria levantar LLMError")
        except LLMError as exc:
            assert chave not in str(exc)
            assert "***" in str(exc)
            assert exc.__cause__ is not None
            assert chave not in str(exc.__cause__)
            assert chave not in "".join(traceback.format_exception(exc))
    assert chave not in caplog.text


# ----------------------------------------------------------------- retry ---


class CapturaPostSequencial:
    """Substitui ``requests.post`` com uma sequência de respostas/exceções."""

    def __init__(self, sequencia: list) -> None:
        self.sequencia = sequencia
        self.chamadas: list[dict] = []

    def __call__(
        self, url: str, headers: dict | None = None, json: dict | None = None, timeout: int | None = None, **kwargs
    ) -> RespostaFalsa:
        self.chamadas.append({"url": url, "headers": headers or {}, "json": json or {}, "timeout": timeout})
        item = self.sequencia[min(len(self.chamadas), len(self.sequencia)) - 1]
        if isinstance(item, Exception):
            raise item
        return item


def test_enviar_post_repete_status_transitorio_e_devolve_sucesso():
    from seguramente_final.motor_llm.base import enviar_post

    sequencia = [RespostaFalsa({}, status=503), RespostaFalsa({}, status=503), RespostaFalsa({"ok": True})]
    captura = CapturaPostSequencial(sequencia)
    esperas: list[float] = []
    resposta = enviar_post(captura, "https://exemplo/v1", dormir=esperas.append)
    assert resposta.json() == {"ok": True}
    assert len(captura.chamadas) == 3
    assert len(esperas) == 2
    assert 1.0 <= esperas[0] < 1.15
    assert 2.0 <= esperas[1] < 2.3  # jitter proporcional: até +15% do backoff


def test_enviar_post_honra_retry_after_do_provedor():
    """429/503 com Retry-After esperam o tempo do provedor (cota por janela)."""
    from seguramente_final.motor_llm.base import enviar_post

    sequencia = [
        RespostaFalsa({}, status=429, headers={"Retry-After": "7"}),
        RespostaFalsa({"ok": True}),
    ]
    captura = CapturaPostSequencial(sequencia)
    esperas: list[float] = []
    resposta = enviar_post(captura, "https://exemplo/v1", dormir=esperas.append, aleatorio=lambda: 0.0)
    assert resposta.json() == {"ok": True}
    assert len(esperas) == 1
    assert esperas[0] == 7.0  # backoff seria 1.0; o provedor manda mais


def test_enviar_post_limita_concorrencia_entre_chamadas(monkeypatch):
    """Fan-out de especialistas não pode disparar requisições ilimitadas (429)."""
    import threading
    import time

    from seguramente_final.motor_llm.base import VARIAVEL_CONCORRENCIA, enviar_post, reiniciar_limitador

    monkeypatch.setenv(VARIAVEL_CONCORRENCIA, "2")
    reiniciar_limitador()
    limite = 2
    simultaneas = 0
    pico = 0
    trinco = threading.Lock()

    def post_lento(url, **kwargs):
        nonlocal simultaneas, pico
        with trinco:
            simultaneas += 1
            pico = max(pico, simultaneas)
        time.sleep(0.05)
        with trinco:
            simultaneas -= 1
        return RespostaFalsa({"ok": True})

    erros: list[BaseException] = []

    def rodar():
        try:
            enviar_post(post_lento, "https://exemplo/v1", tentativas=1)
        except BaseException as exc:  # noqa: BLE001 — coletado e asserado no teste
            erros.append(exc)

    fios = [threading.Thread(target=rodar) for _ in range(limite + 4)]
    try:
        for fio in fios:
            fio.start()
        for fio in fios:
            fio.join()
    finally:
        reiniciar_limitador()

    assert not erros
    assert 1 <= pico <= limite


def test_enviar_post_backoff_respeita_cap():
    """Backoff exponencial não cresce além de ESPERA_MAX (rajadas de 503)."""
    from seguramente_final.motor_llm.base import ESPERA_MAX, TENTATIVAS_PADRAO, enviar_post

    sequencia = [RespostaFalsa({}, status=503) for _ in range(TENTATIVAS_PADRAO)]
    captura = CapturaPostSequencial(sequencia)
    esperas: list[float] = []
    try:
        enviar_post(captura, "https://exemplo/v1", dormir=esperas.append, aleatorio=lambda: 0.0)
    except requests.HTTPError:
        pass
    assert len(esperas) == TENTATIVAS_PADRAO - 1
    assert all(espera <= ESPERA_MAX for espera in esperas)
    assert esperas[-1] == ESPERA_MAX


def test_enviar_post_retry_visivel_em_info(caplog):
    """Em INFO (padrão do Streamlit) o retry precisa aparecer; debug some do log."""
    import logging

    from seguramente_final.motor_llm.base import enviar_post

    sequencia = [RespostaFalsa({}, status=503), RespostaFalsa({"ok": True})]
    captura = CapturaPostSequencial(sequencia)
    with caplog.at_level(logging.INFO, logger="seguramente_final.motor_llm.base"):
        resposta = enviar_post(captura, "https://exemplo/v1", dormir=lambda segundos: None)
    assert resposta.json() == {"ok": True}
    assert "tentativa 1/5" in caplog.text


def test_enviar_post_nao_repete_status_permanente():
    from seguramente_final.motor_llm.base import enviar_post

    captura = CapturaPostSequencial([RespostaFalsa({}, status=400)])
    esperas: list[float] = []
    try:
        enviar_post(captura, "https://exemplo/v1", dormir=esperas.append)
        raise AssertionError("deveria levantar HTTPError")
    except requests.HTTPError:
        pass
    assert len(captura.chamadas) == 1
    assert esperas == []


def test_enviar_post_repete_timeout_ate_sucesso():
    from seguramente_final.motor_llm.base import enviar_post

    sequencia = [requests.Timeout("timeout"), RespostaFalsa({"ok": True})]
    captura = CapturaPostSequencial(sequencia)
    resposta = enviar_post(captura, "https://exemplo/v1", dormir=lambda segundos: None)
    assert resposta.json() == {"ok": True}
    assert len(captura.chamadas) == 2


def test_enviar_post_esgota_tentativas_e_propaga_ultimo_erro():
    from seguramente_final.motor_llm.base import enviar_post

    captura = CapturaPostSequencial([RespostaFalsa({}, status=503)])
    try:
        enviar_post(captura, "https://exemplo/v1", dormir=lambda segundos: None)
        raise AssertionError("deveria levantar HTTPError")
    except requests.HTTPError:
        pass
    assert len(captura.chamadas) == 5


def test_google_chat_json_repete_503_ate_sucesso(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda segundos: None)
    sequencia = [
        RespostaFalsa({}, status=503),
        RespostaFalsa({"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]}),
    ]
    captura = CapturaPostSequencial(sequencia)
    cliente = criar_cliente("google", api_key="g-x", post=captura)
    assert cliente.chat_json([{"role": "user", "content": "oi"}]) == {"ok": True}
    assert len(captura.chamadas) == 2


def test_groq_chat_json_nao_repete_erro_permanente(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda segundos: None)
    captura = CapturaPostSequencial([RespostaFalsa({"error": {"message": "bad request"}}, status=400)])
    cliente = criar_cliente("groq", api_key="gsk-x", post=captura)
    try:
        cliente.chat_json([{"role": "user", "content": "oi"}])
        raise AssertionError("deveria levantar LLMError")
    except LLMError:
        pass
    assert len(captura.chamadas) == 1


def test_provedor_resolve_modelo_do_env_por_provedor(monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", "llama-custom")
    assert criar_cliente("groq").model == "llama-custom"


def test_openai_mantem_compat_seguramente_llm_model(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setenv("SEGURAMENTE_LLM_MODEL", "gpt-legado")
    assert criar_cliente("openai").model == "gpt-legado"
    monkeypatch.setenv("OPENAI_MODEL", "gpt-novo")
    assert criar_cliente("openai").model == "gpt-novo"  # var nova do .env vence a de compat


def test_enviar_post_nao_repete_quando_provedor_pedir_desistir():
    """Cota estourada (espera de horas): a primeira resposta já encerra o retry."""
    from seguramente_final.motor_llm.base import enviar_post
    from seguramente_final.motor_llm.google import cota_esgotada

    corpo_cota = '{"error": {"code": 429, "message": "You exceeded your current quota. '
    corpo_cota += 'Please retry in 11h21.588535867s."}}'
    respostas = [
        RespostaFalsa({"error": {}}, status=429, texto=corpo_cota),
        RespostaFalsa({"ok": True}),
    ]
    captura = CapturaPostSequencial(respostas)
    esperas: list[float] = []
    try:
        enviar_post(captura, "https://exemplo/v1", dormir=esperas.append, nao_repetir=cota_esgotada)
        raise AssertionError("deveria levantar HTTPError")
    except requests.HTTPError:
        pass
    assert len(captura.chamadas) == 1  # não perde ~15s repetindo um 429 de 11h
    assert esperas == []


def test_cota_esgotada_so_aceita_corpo_do_google():
    from seguramente_final.motor_llm.google import cota_esgotada

    assert cota_esgotada(
        RespostaFalsa({}, status=429, texto='{"error": {"message": "You exceeded your current quota"}}')
    )
    assert not cota_esgotada(RespostaFalsa({}, status=429, texto="rate limit exceeded, retry after 2s"))
    assert not cota_esgotada(RespostaFalsa({}, status=429))  # stub sem corpo


def test_google_avisa_cota_esgotada_e_redige_chave():
    from seguramente_final.motor_llm.google import ProvedorGoogle, cota_esgotada

    corpo = (
        '{"error": {"code": 429, "message": "You exceeded your current quota, please check your plan and '
        'billing details. Please retry in 11h21.588535867s."}}'
    )
    resposta = RespostaFalsa({"error": {}}, status=429, texto=corpo)
    cliente = ProvedorGoogle(api_key="g-chave-secreta", model="gemini-x", post=lambda *a, **k: resposta)
    with pytest.raises(LLMError) as erro:
        cliente.chat_json([{"role": "user", "content": "oi"}])
    mensagem = str(erro.value)
    assert "cota gratuita do Google esgotada" in mensagem
    assert "11h21.588535867s" in mensagem
    assert "troque GOOGLE_MODEL" in mensagem
    assert "g-chave-secreta" not in mensagem
    assert cota_esgotada(resposta) is True


def test_modelo_padrao_do_google_e_fonte_unica_do_front():
    """O front e o provedor não podem divergir (o default antigo era 404)."""
    import app
    from seguramente_final.motor_llm.google import ProvedorGoogle

    assert app.MODELOS_PADRAO["google"] == ProvedorGoogle.modelo_padrao
    assert ProvedorGoogle.modelo_padrao != "gemini-2.0-flash"  # removido do catálogo
