"""Interpreta o pedido do usuário: "braço, olho, sol" ou "braço:acenar, sol:girar+pulsar"."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from animacao2d.animacao.catalogo import animacao_padrao_para, resolver_animacao
from animacao2d.util import sem_acentos

_PALAVRAS_VAZIAS = {"o", "a", "os", "as", "um", "uma", "e", "com", "animar", "animacao", "quero", "que", "fique",
                    "fica", "ficar", "deve", "devem", "tambem", "bem", "devagar", "rapido", "lentamente"}


@dataclass
class ItemPedido:
    elemento: str
    animacoes: list[str] = field(default_factory=list)  # vazio = a IA/padrão escolhe

    def animacoes_ou_padrao(self) -> list[str]:
        return self.animacoes or [animacao_padrao_para(self.elemento)]

    def texto(self) -> str:
        return f"{self.elemento}: {'+'.join(self.animacoes)}" if self.animacoes else self.elemento


def interpretar_pedido(texto: str) -> list[ItemPedido]:
    """Divide o pedido em itens; reconhece animações explícitas e verbos no gerúndio."""
    itens: list[ItemPedido] = []
    pedacos = re.split(r"[,;\n]+|\s+e\s+", texto.strip())
    for pedaco in pedacos:
        pedaco = pedaco.strip(" .")
        if not pedaco:
            continue
        animacoes: list[str] = []
        if ":" in pedaco or "=" in pedaco:
            elemento, lista = re.split(r"[:=]", pedaco, maxsplit=1)
            for nome in re.split(r"[+/&]|\s+", lista):
                resolvido = resolver_animacao(nome) if nome.strip() else None
                if resolvido and resolvido not in animacoes:
                    animacoes.append(resolvido)
        else:
            palavras_elemento = []
            for palavra in pedaco.split():
                resolvido = resolver_animacao(palavra)
                if resolvido:
                    if resolvido not in animacoes:
                        animacoes.append(resolvido)
                else:
                    palavras_elemento.append(palavra)
            elemento = " ".join(p for p in palavras_elemento if sem_acentos(p.lower()) not in _PALAVRAS_VAZIAS)
            if not elemento:
                elemento = " ".join(palavras_elemento) or pedaco
        itens.append(ItemPedido(elemento.strip(), animacoes))
    return itens
