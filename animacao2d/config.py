"""Configurações globais (modelo, ritmo das cenas, vídeo) e leitura do .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

MODELO_PADRAO = "claude-opus-5"

# Narração em PT-BR: ~150 palavras por minuto é um ritmo natural de locução/TTS.
PALAVRAS_POR_MINUTO = 150
MINUTOS_PADRAO = 15

# Vídeo de saída
LARGURA_VIDEO = 1920
ALTURA_VIDEO = 1080
FPS = 30


@dataclass(frozen=True)
class Ritmo:
    """Quanto tempo, em média, cada imagem fica na tela."""

    nome: str
    media_s: float
    minimo_s: float
    maximo_s: float
    descricao: str


RITMOS: dict[str, Ritmo] = {
    "rapido": Ritmo("rapido", 3.5, 1.5, 6.0, "troca a cada ~3,5 s (igual ao Crayon Capital, ~250 imagens em 15 min)"),
    "medio": Ritmo("medio", 5.0, 2.0, 9.0, "troca a cada ~5 s (~180 imagens em 15 min)"),
    "calmo": Ritmo("calmo", 7.5, 3.0, 12.0, "troca a cada ~7,5 s (~120 imagens em 15 min)"),
}
RITMO_PADRAO = "medio"


def carregar_env(caminho: str | os.PathLike = ".env") -> None:
    """Lê um arquivo .env simples (CHAVE=valor) sem sobrescrever variáveis já definidas."""
    arquivo = Path(caminho)
    if not arquivo.is_file():
        return
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        chave = chave.strip()
        valor = valor.strip().strip('"').strip("'")
        if chave and chave not in os.environ:
            os.environ[chave] = valor


def modelo_texto() -> str:
    return os.environ.get("ANIMACAO2D_MODELO", "").strip() or MODELO_PADRAO


def modelo_visao() -> str:
    return os.environ.get("ANIMACAO2D_MODELO_VISAO", "").strip() or modelo_texto()


def pasta_projetos() -> Path:
    return Path(os.environ.get("ANIMACAO2D_PASTA_PROJETOS", "").strip() or "projetos")
