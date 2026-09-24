import pytest

from animacao2d.animacao.catalogo import animacao_padrao_para, resolver_animacao, resolver_camera
from animacao2d.animacao.pedido import interpretar_pedido
from animacao2d.util import extrair_json, formatar_srt, formatar_tempo, nome_cena, numero_cena, slugify


@pytest.mark.parametrize("entrada, esperado", [("cena01", 1), ("Cena 7", 7), ("12", 12), ("cena_003.png", 3), (4, 4)])
def test_numero_cena(entrada, esperado):
    assert numero_cena(entrada) == esperado


def test_numero_cena_invalido():
    with pytest.raises(ValueError):
        numero_cena("abacaxi")


def test_nome_e_slug():
    assert nome_cena(3) == "cena03"
    assert nome_cena(120) == "cena120"
    assert slugify("Como a Internet Realmente Funciona?") == "como-a-internet-realmente-funciona"


def test_extrair_json_de_bloco_markdown():
    assert extrair_json('Aqui está:\n```json\n{"a": [1, 2]}\n```') == {"a": [1, 2]}
    assert extrair_json('texto antes {"b": true} texto depois') == {"b": True}


def test_tempos():
    assert formatar_tempo(65.4) == "1:05"
    assert formatar_srt(3661.5) == "01:01:01,500"


@pytest.mark.parametrize("texto, esperado", [
    ("piscando", "piscar"), ("Blink", "piscar"), ("balançar", "balancar"), ("tremendo", "tremer"),
    ("pop", "aparecer"), ("digitar", "codigo"), ("xyz", None),
])
def test_resolver_animacao(texto, esperado):
    assert resolver_animacao(texto) == esperado


def test_camera_e_padroes():
    assert resolver_camera("zoom") == "zoom_in"
    assert resolver_camera(None) == "zoom_in"
    with pytest.raises(ValueError):
        resolver_camera("explodir")
    assert animacao_padrao_para("braço direito do DEV") == "acenar"
    assert animacao_padrao_para("olhos do robô") == "piscar"
    assert animacao_padrao_para("nuvens") == "deslizar"
    assert animacao_padrao_para("tela do notebook") == "codigo"


def test_interpretar_pedido():
    itens = interpretar_pedido("braço, olho e sol")
    assert [(i.elemento, i.animacoes_ou_padrao()) for i in itens] == [
        ("braço", ["acenar"]), ("olho", ["piscar"]), ("sol", ["girar"])]
    itens = interpretar_pedido("lâmpada: brilhar+flutuar; o braço acenando")
    assert itens[0].animacoes == ["brilhar", "flutuar"]
    assert (itens[1].elemento, itens[1].animacoes) == ("braço", ["acenar"])


def test_aviso_proporcao_16_9():
    from animacao2d.animacao.imagem import aviso_proporcao

    assert aviso_proporcao(1920, 1080) is None
    assert aviso_proporcao(1456, 816) is None  # Midjourney --ar 16:9
    assert aviso_proporcao(1792, 1024) is None  # DALL-E paisagem (quase 16:9)
    assert "não é 16:9" in aviso_proporcao(1024, 1024)
    assert "cortado nas laterais" in aviso_proporcao(3000, 1000)


def test_estilo_pede_16_9_e_expressoes_exageradas():
    from animacao2d.estilo import ESTILO_PADRAO, SUFIXO_MIDJOURNEY_PADRAO

    assert "16:9" in ESTILO_PADRAO and "--ar 16:9" in SUFIXO_MIDJOURNEY_PADRAO
    assert "EXAGGERATED" in ESTILO_PADRAO
