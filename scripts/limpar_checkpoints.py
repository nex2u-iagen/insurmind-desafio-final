#!/usr/bin/env python3
"""Poda checkpoints do grafo sem atividade recente (crescem a cada análise).

Uso:
    python scripts/limpar_checkpoints.py --dias 7 --dry-run   # só lista
    python scripts/limpar_checkpoints.py --dias 7             # apaga
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from seguramente_final.agentes.checkpoint_epoch import podar_checkpoints  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dias", type=int, default=7, help="Idade mínima da thread em dias (default: 7)")
    parser.add_argument("--diretorio", default=str(ROOT / "data"), help="Raiz de dados (default: data)")
    parser.add_argument("--dry-run", action="store_true", help="Lista sem apagar")
    args = parser.parse_args()
    threads = podar_checkpoints(args.diretorio, args.dias, dry_run=args.dry_run)
    acao = "seriam removidas" if args.dry_run else "removidas"
    print(f"{len(threads)} thread(s) {acao}: {', '.join(threads) or '(nenhuma)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
