import re

from animacao2d.cenas import (dividir_em_trechos, montar_prompt, reparar_grupos, srt_legendas, texto_da_narracao)
from animacao2d.roteiro import Personagem, Roteiro, Secao
from animacao2d.util import contar_palavras

TEXTO = """Em 1991, um estudante finlandês de 21 anos mandou uma mensagem despretensiosa para um fórum da \
internet, dizendo que estava fazendo um sistema operacional só por hobby, nada grande nem profissional. \
Trinta anos depois, esse hobby roda em quase todos os servidores do planeta!

DEV: Espera. O Android também?

CHEFE: Também. E a sua geladeira inteligente, provavelmente.

Mas como um projeto de fim de semana virou a base da internet?"""


def test_trechos_nao_perdem_palavras():
    trechos = dividir_em_trechos(TEXTO, 12)
    originais = re.sub(r"^[A-Z]+:\s*", "", TEXTO, flags=re.M).split()
    assert " ".join(t.texto for t in trechos).split() == originais
    assert all(t.palavras <= 17 for t in trechos)
    assert [t.falante for t in trechos if t.falante] == ["DEV", "DEV", "CHEFE", "CHEFE"]
    # não corta no meio de "fim de semana"
    assert any("fim de semana" in t.texto for t in trechos)


def test_narracao_repete_tag_so_quando_muda():
    trechos = dividir_em_trechos(TEXTO, 12)
    texto = texto_da_narracao([t for t in trechos if t.falante])
    assert texto == "DEV: Espera. O Android também?\nCHEFE: Também. E a sua geladeira inteligente, provavelmente."


def test_reparar_grupos_cobre_tudo():
    grupos = reparar_grupos([{"inicio": 2, "fim": 3}, {"inicio": 3, "fim": 5}, {"inicio": 8, "fim": 9},
                             {"inicio": 7, "fim": 4}], 10)
    cobertos = [n for g in grupos for n in range(g["inicio"], g["fim"] + 1)]
    assert cobertos == list(range(1, 11))


def test_montar_prompt_troca_tags_e_artigos():
    prompt = montar_prompt("The [DEV] points at [cpu], huge and sweating", {"DEV": "a young dev", "CPU": "a chip"},
                           "flat style")
    assert prompt == "a young dev points at a chip, huge and sweating. flat style"


def test_roteiro_markdown_ida_e_volta():
    roteiro = Roteiro("Título", "Descrição", [Personagem("DEV", "Dev", "programador", "a young dev, green hoodie")],
                      [Secao("Gancho", "gancho", "Primeira frase.\n\nDEV: Fala."), Secao("Parte 1", "capitulo", "Texto.")])
    de_volta = Roteiro.de_markdown(roteiro.para_markdown())
    assert de_volta.para_dict() == roteiro.para_dict()
    assert de_volta.palavras == contar_palavras("Primeira frase. Fala. Texto.") + 0


def test_legendas_srt():
    plano = {"cenas": [{"narracao": "DEV: " + "palavra " * 30, "inicio_s": 0.0, "duracao": 6.0}]}
    srt = srt_legendas(plano)
    blocos = [b for b in srt.strip().split("\n\n") if b]
    assert len(blocos) >= 2
    assert "DEV:" not in srt
    assert blocos[0].startswith("1\n00:00:00,000 --> ")
