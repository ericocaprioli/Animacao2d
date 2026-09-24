"""Leitura/gravação de imagens (via Pillow, funciona com acentos no caminho no Windows)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

EXTENSOES = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def carregar_rgb(caminho: str | Path) -> np.ndarray:
    """Carrega como RGB uint8 (transparência vira fundo branco)."""
    with Image.open(caminho) as img:
        img.load()
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            fundo = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            fundo.alpha_composite(rgba)
            img = fundo
        return np.ascontiguousarray(np.asarray(img.convert("RGB")))


def tamanho_imagem(caminho: str | Path) -> tuple[int, int]:
    with Image.open(caminho) as img:
        return img.size


def salvar_rgb(caminho: str | Path, rgb: np.ndarray) -> None:
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.ascontiguousarray(rgb)).save(caminho)


PROPORCAO_VIDEO = 16 / 9


def aviso_proporcao(largura: int, altura: int, nome: str = "A imagem") -> str | None:
    """Mensagem se a imagem não for 16:9 (o vídeo do YouTube é 16:9 e ela seria cortada)."""
    if not largura or not altura:
        return None
    proporcao = largura / altura
    if abs(proporcao - PROPORCAO_VIDEO) / PROPORCAO_VIDEO <= 0.03:
        return None
    corte = 1 - min(proporcao, PROPORCAO_VIDEO) / max(proporcao, PROPORCAO_VIDEO)
    lado = "em cima e embaixo" if proporcao < PROPORCAO_VIDEO else "nas laterais"
    return (f"{nome} tem {largura}x{altura} (proporção {proporcao:.2f}:1), não é 16:9. Para preencher o vídeo "
            f"16:9 do YouTube, {corte:.0%} dela será cortado {lado}. Gere em 16:9 (ex.: 1920x1080, 1456x816 "
            "ou --ar 16:9 no Midjourney).")
