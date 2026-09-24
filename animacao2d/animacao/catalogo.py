"""Catálogo de animações simples e movimentos de câmera.

Cada animação é de um de dois tipos:
- "movimento": a parte é recortada da imagem e se move (o buraco atrás dela é
  preenchido automaticamente);
- "pintura": o efeito é desenhado no lugar (piscar, falar, brilhar...).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from animacao2d.util import sem_acentos


@dataclass(frozen=True)
class TipoAnimacao:
    nome: str
    categoria: str  # "movimento" | "pintura"
    descricao: str
    exemplos: str
    pivo: str  # onde fica o pivô padrão: centro | base | topo | manual | nenhum
    mascara: str  # recorte padrão: auto | caixa | elipse
    aliases: tuple[str, ...] = ()


ANIMACOES: dict[str, TipoAnimacao] = {
    t.nome: t
    for t in [
        TipoAnimacao("piscar", "pintura", "pisca de tempos em tempos", "olhos (uma parte para cada olho)",
                     "nenhum", "caixa", ("blink", "piscada", "pisca")),
        TipoAnimacao("falar", "pintura", "abre e fecha a boca como se estivesse falando", "boca",
                     "nenhum", "caixa", ("talk", "fala", "conversar")),
        TipoAnimacao("acenar", "movimento", "vai e volta girando a partir do pivô (ombro ou pulso)",
                     "braço, mão", "manual", "auto", ("wave", "tchau", "aceno", "mexer")),
        TipoAnimacao("balancar", "movimento", "balanço lento e suave a partir do pivô",
                     "perna, cabeça, árvore, placa pendurada, rabo", "base", "auto",
                     ("sway", "swing", "balanco", "pendulo", "sacudir")),
        TipoAnimacao("girar", "movimento", "rotação contínua em torno do centro",
                     "sol, engrenagem, roda, ventilador, ponteiro", "centro", "auto",
                     ("spin", "rotate", "rodar", "rotacao", "giro")),
        TipoAnimacao("pulsar", "movimento", "cresce e volta ao tamanho, como uma batida",
                     "coração, ícone, botão, alerta", "centro", "auto", ("pulse", "pulso", "batida", "bater")),
        TipoAnimacao("flutuar", "movimento", "sobe e desce devagar", "nuvem, moeda, balão, ícone",
                     "centro", "auto", ("float", "bob", "boiar", "levitar", "subir")),
        TipoAnimacao("deslizar", "movimento", "atravessa a cena devagar (direita por padrão)",
                     "nuvem, carro, pássaro, avião", "centro", "auto",
                     ("drift", "slide", "andar", "passar", "mover", "correr", "voar")),
        TipoAnimacao("tremer", "movimento", "tremida nervosa", "personagem assustado, alarme, celular vibrando",
                     "centro", "auto", ("shake", "tremor", "vibrar", "tremedeira")),
        TipoAnimacao("aparecer", "movimento", "surge com um 'pop' elástico (use 'atraso' para o momento)",
                     "ícones, setas, moedas, objetos que entram na cena", "centro", "auto",
                     ("pop", "surgir", "entrar", "popin")),
        TipoAnimacao("respirar", "movimento", "respiração sutil, estica levemente para cima",
                     "personagem inteiro, corpo", "base", "auto", ("breathe", "respiracao")),
        TipoAnimacao("brilhar", "pintura", "brilho pulsante com halo de luz", "lâmpada, estrela, tela, fogo, ideia",
                     "centro", "auto", ("glow", "brilho", "acender", "piscar-luz", "reluzir")),
        TipoAnimacao("ondular", "pintura", "distorção em onda", "bandeira, água, fogo, cabelo, fumaça",
                     "nenhum", "caixa", ("wave-warp", "ondulacao", "onda", "tremular")),
        TipoAnimacao("codigo", "pintura", "linhas de código sendo digitadas dentro de uma tela",
                     "tela de computador, monitor, celular", "nenhum", "caixa",
                     ("digitar", "programar", "code", "typing", "codar")),
    ]
}

ANIMACOES_MOVIMENTO = [n for n, t in ANIMACOES.items() if t.categoria == "movimento"]
ANIMACOES_PINTURA = [n for n, t in ANIMACOES.items() if t.categoria == "pintura"]

CAMERAS: dict[str, str] = {
    "zoom_in": "aproxima devagar (padrão)",
    "zoom_out": "afasta devagar",
    "pan_esquerda": "passeia para a esquerda",
    "pan_direita": "passeia para a direita",
    "pan_cima": "passeia para cima",
    "pan_baixo": "passeia para baixo",
    "zoom_rapido": "zoom rápido no começo (ênfase, piada, revelação)",
    "tremor": "câmera tremendo (impacto, tensão, caos)",
    "parado": "sem movimento",
}
CAMERA_PADRAO = "zoom_in"

_ALIASES_CAMERA = {
    "zoom": "zoom_in", "aproximar": "zoom_in", "zoomin": "zoom_in", "zoom-in": "zoom_in",
    "afastar": "zoom_out", "zoomout": "zoom_out", "zoom-out": "zoom_out",
    "pan": "pan_direita", "esquerda": "pan_esquerda", "direita": "pan_direita",
    "cima": "pan_cima", "baixo": "pan_baixo", "estatica": "parado", "fixa": "parado", "nenhum": "parado",
    "punch": "zoom_rapido", "shake": "tremor", "tremida": "tremor",
}

# Palavra do elemento -> animação padrão (usado quando o pedido não diz a animação)
ELEMENTO_PADRAO: dict[str, str] = {}
for _animacao, _palavras in {
    "piscar": "olho olhos olhinho olhinhos eye eyes",
    "falar": "boca bocas labio labios mouth",
    "acenar": "braco bracos mao maos antebraco arm hand",
    "balancar": "perna pernas pe pes cabeca rabo cauda arvore arvores folha folhas planta plantas placa galho "
                "pendulo cabelo_preso orelha orelhas antena antenas",
    "girar": "sol engrenagem engrenagens roda rodas ventilador helice helices ponteiro ponteiros cata-vento "
             "catavento moinho disco pneu gear sun wheel",
    "pulsar": "coracao coracoes icone icones botao botoes alerta exclamacao relogio simbolo logo emoji heart",
    "flutuar": "moeda moedas dinheiro nota notas balao baloes fantasma bolha bolhas pena interrogacao "
               "dolar coin cifrao",
    "deslizar": "nuvem nuvens carro carros passaro passaros aviao avioes onibus trem barco navio foguete "
                "caminhao moto bicicleta cloud car",
    "tremer": "alarme bomba despertador raio terremoto",
    "respirar": "personagem personagens corpo pessoa homem mulher menino menina robo crianca velho velha "
                "cachorro gato",
    "brilhar": "lampada estrela estrelas luz luzes celular chip cpu gpu servidor cristal diamante ouro "
               "tesouro ideia farol vela neon",
    "ondular": "bandeira agua fogo chama chamas fumaca mar rio lago onda cachoeira cabelo capa",
    "codigo": "tela telas monitor monitores computador computadores notebook laptop terminal codigo pc",
    "aparecer": "seta setas grafico graficos balaozinho check",
}.items():
    for _p in _palavras.split():
        ELEMENTO_PADRAO[_p.replace("_", " ")] = _animacao


def _normalizar(texto: str) -> str:
    return sem_acentos(texto).lower().strip()


def _indice_aliases() -> dict[str, str]:
    indice: dict[str, str] = {}
    for nome, tipo in ANIMACOES.items():
        indice[nome] = nome
        for alias in tipo.aliases:
            indice[_normalizar(alias)] = nome
    return indice


_INDICE = _indice_aliases()


def resolver_animacao(texto: str) -> str | None:
    """'piscando', 'Blink', 'balançar' -> nome canônico (ou None)."""
    chave = _normalizar(texto).replace(" ", "-")
    if chave in _INDICE:
        return _INDICE[chave]
    # gerúndio -> infinitivo: acenando -> acenar, tremendo -> tremer, surgindo -> surgir
    for fim, troca in (("ando", "ar"), ("endo", "er"), ("indo", "ir")):
        if chave.endswith(fim):
            infinitivo = chave[: -len(fim)] + troca
            if infinitivo in _INDICE:
                return _INDICE[infinitivo]
    return None


def resolver_camera(texto: str | None) -> str:
    if not texto:
        return CAMERA_PADRAO
    chave = _normalizar(texto).replace(" ", "_")
    if chave in CAMERAS:
        return chave
    chave2 = chave.replace("_", "")
    if chave2 in _ALIASES_CAMERA:
        return _ALIASES_CAMERA[chave2]
    if chave in _ALIASES_CAMERA:
        return _ALIASES_CAMERA[chave]
    raise ValueError(f"Movimento de câmera desconhecido: '{texto}'. Opções: {', '.join(CAMERAS)}")


def animacao_padrao_para(elemento: str) -> str:
    """Escolhe uma animação pelo nome do elemento ('braço do dev' -> acenar)."""
    palavras = re.findall(r"[a-z0-9\-]+", _normalizar(elemento))
    for palavra in palavras:
        if palavra in ELEMENTO_PADRAO:
            return ELEMENTO_PADRAO[palavra]
        if palavra.endswith("s") and palavra[:-1] in ELEMENTO_PADRAO:
            return ELEMENTO_PADRAO[palavra[:-1]]
    return "flutuar"


def texto_catalogo() -> str:
    """Tabela legível do catálogo (usada na CLI e nos prompts da IA)."""
    linhas = []
    for nome, t in ANIMACOES.items():
        linhas.append(f"- {nome}: {t.descricao}. Bom para: {t.exemplos}.")
    return "\n".join(linhas)


def texto_cameras() -> str:
    return "\n".join(f"- {nome}: {desc}" for nome, desc in CAMERAS.items())
