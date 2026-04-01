from __future__ import annotations
import json
from pathlib import Path
import re

class TermPostProcessor:
    """Simple glossary-based postprocess before TTS.

    Glossary format (JSON):
      {
        "replacement_rules": [
          {"pattern": "NaCl", "replace": "氯化钠"},
          {"pattern": "CO2", "replace": "二氧化碳"}
        ]
      }
    """
    def __init__(self, glossary_dir: str = "glossary"):
        self.rules: list[tuple[re.Pattern, str]] = []
        self._load(glossary_dir)

    def _load(self, glossary_dir: str):
        gdir = Path(glossary_dir)
        if not gdir.exists():
            return
        for fp in gdir.glob("*.json"):
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
                for r in data.get("replacement_rules", []):
                    pat = re.compile(r["pattern"])
                    rep = r["replace"]
                    self.rules.append((pat, rep))
            except Exception:
                continue

    def __call__(self, text: str) -> str:
        out = text
        for pat, rep in self.rules:
            out = pat.sub(rep, out)
        return out
