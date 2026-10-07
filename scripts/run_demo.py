#!/usr/bin/env python3
"""Executa e registra uma análise comparativa de duas apólices D&O."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from seguramente_final.pipeline import analyze_policies  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["offline", "openai", "groq", "google"], default="offline")
    parser.add_argument("--output", default="evidence/demo_analysis.json")
    args = parser.parse_args()
    result = analyze_policies(
        [ROOT / "data" / "policies" / "Apolice_DO_A.pdf", ROOT / "data" / "policies" / "Apolice_DO_B.pdf"],
        names=["Apólice A", "Apólice B"],
        source="Corpus sintético autoral — uso didático",
        provider_mode=args.provider,
        store_path=ROOT / "data" / "policies.db",
    )
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    differences = [row for row in result.comparison if row.status not in {"igual", "ambos_ausentes"}]
    try:
        rotulo = str(output.relative_to(ROOT))
    except ValueError:  # --output fora do repositório (ex.: /tmp)
        rotulo = str(output)
    print(
        json.dumps(
            {
                "output": rotulo,
                "documents": len(result.documents),
                "pages": sum(len(doc.pages) for doc in result.documents),
                "fields": len(result.comparison),
                "differences_or_gaps": len(differences),
                "provider": result.provider,
                "model": result.model,
                "fallback_offline": result.fallback_offline,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
