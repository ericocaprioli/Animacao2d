import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture
def imagem_exemplo(tmp_path):
    from animacao2d.exemplo import SPEC_EXEMPLO, desenhar
    from animacao2d.util import salvar_json

    imagem = tmp_path / "cena01.png"
    desenhar().save(imagem)
    salvar_json(tmp_path / "cena01.json", SPEC_EXEMPLO)
    return imagem


@pytest.fixture
def ambiente_isolado(tmp_path, monkeypatch):
    """Pasta de trabalho limpa, sem .env nem projeto anterior."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANIMACAO2D_PASTA_PROJETOS", str(tmp_path / "projetos"))
    monkeypatch.setenv("ANIMACAO2D_NAO_ABRIR", "1")
    for variavel in ("ANIMACAO2D_MODELO", "ANIMACAO2D_MODELO_VISAO", "ANIMACAO2D_TEXTO", "ANIMACAO2D_IA",
                     "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(variavel, raising=False)
    return tmp_path
