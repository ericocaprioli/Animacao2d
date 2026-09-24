"""Motor de animação 2D: recorta partes de uma ilustração e as anima."""

from animacao2d.animacao.catalogo import ANIMACOES, CAMERAS, animacao_padrao_para, resolver_animacao
from animacao2d.animacao.render import RenderizadorCena, renderizar_cena
from animacao2d.animacao.spec import Camera, ErroSpec, Parte, SpecCena

__all__ = [
    "ANIMACOES",
    "CAMERAS",
    "Camera",
    "ErroSpec",
    "Parte",
    "RenderizadorCena",
    "SpecCena",
    "animacao_padrao_para",
    "renderizar_cena",
    "resolver_animacao",
]
