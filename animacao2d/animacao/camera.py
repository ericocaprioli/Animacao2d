"""Movimentos de câmera (Ken Burns): zoom, pan, zoom rápido e tremor."""

from __future__ import annotations

import math

import numpy as np

from animacao2d.animacao.spec import Camera


def _ruido(t: float, fase: float) -> float:
    return 0.6 * math.sin(2 * math.pi * 7.3 * t + fase) + 0.4 * math.sin(2 * math.pi * 11.9 * t + 2.1 * fase)


def matriz_camera(camera: Camera, t: float, duracao: float, largura_fonte: int, altura_fonte: int,
                  largura_saida: int, altura_saida: int, foco: tuple[float, float] | None = None) -> np.ndarray:
    """Matriz afim 2x3 que leva a imagem de trabalho para o quadro de saída."""
    base = max(largura_saida / largura_fonte, altura_saida / altura_fonte)  # preenche a tela (cover)
    u = 0.0 if duracao <= 0 else min(1.0, max(0.0, t / duracao))
    forca = max(0.0, camera.intensidade)
    cx, cy = foco if foco is not None else (largura_fonte / 2.0, altura_fonte / 2.0)
    zoom = 1.0
    movimento = camera.movimento

    if movimento == "zoom_in":
        zoom = 1.0 + 0.10 * forca * u
    elif movimento == "zoom_out":
        zoom = 1.0 + 0.10 * forca * (1.0 - u)
    elif movimento == "zoom_rapido":
        rapido = 1.0 - (1.0 - min(1.0, t / 0.35)) ** 3
        zoom = 1.0 + 0.16 * forca * rapido + 0.03 * forca * u
    elif movimento in ("pan_esquerda", "pan_direita", "pan_cima", "pan_baixo"):
        zoom = 1.0 + 0.10 * max(0.3, forca)
    elif movimento == "tremor":
        zoom = 1.05

    escala = base * zoom
    meia_l = largura_saida / (2.0 * escala)
    meia_a = altura_saida / (2.0 * escala)
    folga_x = max(0.0, largura_fonte / 2.0 - meia_l)
    folga_y = max(0.0, altura_fonte / 2.0 - meia_a)

    if movimento == "pan_esquerda":
        cx = largura_fonte / 2.0 + folga_x * (1.0 - 2.0 * u)
    elif movimento == "pan_direita":
        cx = largura_fonte / 2.0 - folga_x * (1.0 - 2.0 * u)
    elif movimento == "pan_cima":
        cy = altura_fonte / 2.0 + folga_y * (1.0 - 2.0 * u)
    elif movimento == "pan_baixo":
        cy = altura_fonte / 2.0 - folga_y * (1.0 - 2.0 * u)
    elif movimento == "tremor":
        amplitude = 0.006 * largura_fonte * forca
        cx += amplitude * _ruido(t, 0.3)
        cy += amplitude * _ruido(t, 1.7)

    # nunca mostra fora da imagem
    cx = float(np.clip(cx, meia_l, largura_fonte - meia_l)) if largura_fonte > 2 * meia_l else largura_fonte / 2.0
    cy = float(np.clip(cy, meia_a, altura_fonte - meia_a)) if altura_fonte > 2 * meia_a else altura_fonte / 2.0
    return np.array(
        [[escala, 0.0, largura_saida / 2.0 - escala * cx],
         [0.0, escala, altura_saida / 2.0 - escala * cy]],
        dtype=np.float64,
    )
