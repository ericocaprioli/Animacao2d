"""Cena de exemplo desenhada por código (estilo vetor chapado com contorno).

Usada pelo comando `animacao2d exemplo` e pelos testes: não precisa de IA nem
de imagens externas.
"""

from __future__ import annotations

import json
import math

from PIL import Image, ImageDraw

L, A = 1456, 816  # tamanho padrão 16:9 do Midjourney
S = 2  # desenha em 2x e reduz (antisserrilhado)
CONTORNO = (34, 34, 38)
TRACO = 5 * S


def p(*valores: float) -> list[float]:
    return [v * S for v in valores]


def desenhar() -> Image.Image:
    img = Image.new("RGB", (L * S, A * S), (169, 203, 224))
    d = ImageDraw.Draw(img)
    # chão
    d.rectangle(p(0, 590, L, A), fill=(216, 203, 181))
    d.line(p(0, 590, L, 590), fill=CONTORNO, width=TRACO)

    # sol com raios
    cx, cy, r = 1240, 140, 55
    for k in range(12):
        ang = k * math.pi / 6
        d.line(p(cx + 72 * math.cos(ang), cy + 72 * math.sin(ang), cx + 100 * math.cos(ang), cy + 100 * math.sin(ang)),
               fill=CONTORNO, width=TRACO + 10 * S)
        d.line(p(cx + 72 * math.cos(ang), cy + 72 * math.sin(ang), cx + 100 * math.cos(ang), cy + 100 * math.sin(ang)),
               fill=(242, 193, 78), width=10 * S)
    d.ellipse(p(cx - r, cy - r, cx + r, cy + r), fill=(242, 193, 78), outline=CONTORNO, width=TRACO)

    # nuvem
    for x0, y0, x1, y1 in [(225, 110, 335, 180), (285, 80, 395, 170), (345, 105, 445, 180)]:
        d.ellipse(p(x0, y0, x1, y1), fill=CONTORNO)
    for x0, y0, x1, y1 in [(230, 115, 330, 175), (290, 85, 390, 165), (350, 110, 440, 175)]:
        d.ellipse(p(x0, y0, x1, y1), fill=(244, 241, 234))

    # mesa + monitor
    d.rectangle(p(820, 470, 1260, 500), fill=(139, 107, 78), outline=CONTORNO, width=TRACO)
    for x in (850, 1210):
        d.rectangle(p(x, 500, x + 22, 640), fill=(139, 107, 78), outline=CONTORNO, width=TRACO)
    d.rectangle(p(1022, 438, 1058, 472), fill=(90, 96, 108), outline=CONTORNO, width=TRACO)
    d.rounded_rectangle(p(898, 248, 1182, 442), radius=14 * S, fill=(61, 68, 80), outline=CONTORNO, width=TRACO)
    d.rectangle(p(918, 268, 1162, 422), fill=(39, 48, 64))

    # lâmpada (ideia)
    d.rounded_rectangle(p(645, 178, 675, 210), radius=6 * S, fill=(150, 150, 150), outline=CONTORNO, width=TRACO)
    d.ellipse(p(622, 100, 698, 182), fill=(252, 227, 138), outline=CONTORNO, width=TRACO)

    # personagem: pernas
    for x0, x1 in ((497, 490), (547, 556)):
        d.line(p(x0, 510, x1, 640), fill=CONTORNO, width=34 * S)
        d.line(p(x0, 510, x1, 640), fill=(90, 95, 102), width=24 * S)
        d.ellipse(p(x1 - 26, 628, x1 + 26, 660), fill=(60, 60, 64), outline=CONTORNO, width=TRACO)
    # braço abaixado
    d.line(p(578, 370, 618, 470), fill=CONTORNO, width=36 * S)
    d.line(p(578, 370, 618, 470), fill=(107, 143, 113), width=26 * S)
    d.ellipse(p(598, 458, 640, 500), fill=(241, 211, 181), outline=CONTORNO, width=TRACO)
    # braço levantado (acenando)
    d.line(p(465, 372, 392, 248), fill=CONTORNO, width=36 * S)
    d.line(p(465, 372, 392, 248), fill=(107, 143, 113), width=26 * S)
    d.ellipse(p(355, 196, 407, 248), fill=(241, 211, 181), outline=CONTORNO, width=TRACO)
    # tronco (moletom)
    d.rounded_rectangle(p(452, 335, 590, 525), radius=40 * S, fill=(107, 143, 113), outline=CONTORNO, width=TRACO)
    # cabeça de feijão
    d.ellipse(p(446, 160, 598, 345), fill=(241, 211, 181), outline=CONTORNO, width=TRACO)
    d.chord(p(446, 160, 598, 300), start=180, end=360, fill=(58, 46, 40), outline=CONTORNO, width=TRACO)
    # olhos e boca
    for ex in (495, 548):
        d.ellipse(p(ex - 8, 247, ex + 8, 263), fill=CONTORNO)
    d.arc(p(503, 272, 543, 300), start=20, end=160, fill=CONTORNO, width=4 * S)

    return img.resize((L, A), Image.LANCZOS)


SPEC_EXEMPLO = json.loads(r"""{
  "versao": 1,
  "cena": 1,
  "imagem": "cena01.png",
  "largura": 1456,
  "altura": 816,
  "duracao": 6.0,
  "camera": {
    "movimento": "zoom_in",
    "intensidade": 1.0
  },
  "partes": [
    {
      "nome": "braço levantado",
      "animacoes": ["acenar"],
      "caixa": [348, 190, 478, 385],
      "pivo": [462, 368],
      "mascara": "auto",
      "intensidade": 1.0,
      "velocidade": 1.0,
      "atraso": 0.0
    },
    {
      "nome": "olho esquerdo",
      "animacoes": ["piscar"],
      "caixa": [484, 244, 506, 266],
      "mascara": "caixa",
      "intensidade": 1.0,
      "velocidade": 1.0,
      "atraso": 0.0
    },
    {
      "nome": "olho direito",
      "animacoes": ["piscar"],
      "caixa": [537, 244, 559, 266],
      "mascara": "caixa",
      "intensidade": 1.0,
      "velocidade": 1.0,
      "atraso": 0.0
    },
    {
      "nome": "boca",
      "animacoes": ["falar"],
      "caixa": [500, 278, 546, 304],
      "mascara": "caixa",
      "intensidade": 1.0,
      "velocidade": 1.0,
      "atraso": 0.0
    },
    {
      "nome": "sol",
      "animacoes": ["girar", "pulsar"],
      "caixa": [1135, 35, 1345, 245],
      "mascara": "auto",
      "intensidade": 1.0,
      "velocidade": 1.0,
      "atraso": 0.0
    },
    {
      "nome": "nuvem",
      "animacoes": ["deslizar"],
      "caixa": [220, 75, 450, 185],
      "mascara": "auto",
      "intensidade": 1.0,
      "velocidade": 1.0,
      "atraso": 0.0
    },
    {
      "nome": "lâmpada",
      "animacoes": ["brilhar", "flutuar"],
      "caixa": [615, 95, 705, 215],
      "mascara": "auto",
      "intensidade": 1.0,
      "velocidade": 1.0,
      "atraso": 0.0
    },
    {
      "nome": "tela do computador",
      "animacoes": ["codigo"],
      "caixa": [918, 268, 1162, 422],
      "mascara": "caixa",
      "intensidade": 1.0,
      "velocidade": 1.0,
      "atraso": 0.5
    }
  ]
}
""")
