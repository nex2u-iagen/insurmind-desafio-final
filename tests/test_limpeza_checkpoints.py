"""Testes da poda de checkpoints do grafo (crescem a cada análise)."""

from __future__ import annotations

import os
import time

import pytest

from seguramente_final.agentes.checkpoint_epoch import podar_checkpoints

ANTIGO = 10 * 86_400


def _criar_thread(raiz, nome: str, idade_segundos: float) -> None:
    thread = raiz / "checkpoints" / nome
    thread.mkdir(parents=True)
    arquivo = thread / "abc.ckpt.json"
    arquivo.write_text("{}", encoding="utf-8")
    os.utime(arquivo, (time.time() - idade_segundos, time.time() - idade_segundos))


def test_poda_remove_somente_threads_antigas(tmp_path):
    _criar_thread(tmp_path, "velha", ANTIGO)
    _criar_thread(tmp_path, "recente", 60)

    removidas = podar_checkpoints(tmp_path, dias=7)

    assert removidas == ["velha"]
    assert not (tmp_path / "checkpoints" / "velha").exists()
    assert (tmp_path / "checkpoints" / "recente").exists()


def test_dry_run_lista_sem_apagar(tmp_path):
    _criar_thread(tmp_path, "velha", ANTIGO)

    removidas = podar_checkpoints(tmp_path, dias=7, dry_run=True)

    assert removidas == ["velha"]
    assert (tmp_path / "checkpoints" / "velha").exists()


def test_poda_sem_checkpoints_retorna_vazio(tmp_path):
    assert podar_checkpoints(tmp_path, dias=7) == []


def test_poda_dias_negativos_levanta_valueerror(tmp_path):
    with pytest.raises(ValueError, match="dias"):
        podar_checkpoints(tmp_path, dias=-1)
