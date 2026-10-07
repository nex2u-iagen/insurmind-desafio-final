"""Testes TDD da persistência de chaves/modelos do front no .env (fora do git)."""

from __future__ import annotations

import os
import stat

from dotenv import dotenv_values

from seguramente_final.motor_llm.chaves import caminho_env, chaves_salvas, gravar_chaves


def test_caminho_env_respeita_variavel_de_ambiente(tmp_path, monkeypatch):
    alvo = tmp_path / "custom.env"
    monkeypatch.setenv("SEGURAMENTE_ENV_FILE", str(alvo))
    assert caminho_env() == alvo


def test_gravar_chaves_cria_e_atualiza_preservando_o_resto(tmp_path, monkeypatch):
    alvo = tmp_path / ".env"
    alvo.write_text("OPENAI_API_KEY='antiga'\nOUTRA_VAR=1\n", encoding="utf-8")
    monkeypatch.setenv("SEGURAMENTE_ENV_FILE", str(alvo))

    gravar_chaves("openai", modelo="gpt-x", api_key="sk-nova-123")

    valores = dotenv_values(alvo)
    assert valores["OPENAI_API_KEY"] == "sk-nova-123"
    assert valores["OPENAI_MODEL"] == "gpt-x"
    assert valores["OUTRA_VAR"] == "1"  # variável alheia preservada
    assert alvo.read_text(encoding="utf-8").count("OPENAI_API_KEY") == 1  # sem duplicar


def test_gravar_chaves_ignora_valores_vazios(tmp_path, monkeypatch):
    alvo = tmp_path / ".env"
    monkeypatch.setenv("SEGURAMENTE_ENV_FILE", str(alvo))

    gravar_chaves("groq", modelo="   ", api_key=None)

    assert not alvo.exists()  # nada a gravar → não cria arquivo


def test_gravar_chaves_grava_modelo_sem_chave(tmp_path, monkeypatch):
    alvo = tmp_path / ".env"
    monkeypatch.setenv("SEGURAMENTE_ENV_FILE", str(alvo))

    gravar_chaves("google", modelo="gemini-x", api_key=None)

    valores = chaves_salvas()
    assert valores["GOOGLE_MODEL"] == "gemini-x"
    assert "GOOGLE_API_KEY" not in valores


def test_arquivo_env_fica_com_permissao_de_dono(tmp_path, monkeypatch):
    monkeypatch.setenv("SEGURAMENTE_ENV_FILE", str(tmp_path / ".env"))

    gravar_chaves("groq", api_key="g-secret")

    modo = stat.S_IMODE(os.stat(caminho_env()).st_mode)
    assert modo == 0o600
