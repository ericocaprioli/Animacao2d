"""Gera exemplos/cena01.png e exemplos/cena01.json (a cena de exemplo do README).

    python exemplos/gerar_exemplo.py
    animacao2d animar exemplos/cena01.png
"""

import json
from pathlib import Path

from animacao2d.exemplo import SPEC_EXEMPLO, desenhar

if __name__ == "__main__":
    pasta = Path(__file__).resolve().parent
    desenhar().save(pasta / "cena01.png")
    (pasta / "cena01.json").write_text(json.dumps(SPEC_EXEMPLO, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Exemplo salvo em {pasta}")
