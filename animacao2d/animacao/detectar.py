"""Localiza na imagem as partes pedidas ("braço, olho, sol") usando o Claude.

Sem IA, cria caixas provisórias para você posicionar no editor visual.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from animacao2d.animacao.catalogo import ANIMACOES, CAMERAS, texto_cameras, texto_catalogo
from animacao2d.animacao.imagem import carregar_rgb
from animacao2d.animacao.pedido import ItemPedido, interpretar_pedido
from animacao2d.animacao.spec import Camera, Parte, SpecCena
from animacao2d.llm import ClienteIA, bloco_imagem, bloco_texto

LADO_MAXIMO_ENVIO = 1920  # px no lado maior da imagem enviada à IA

SCHEMA_DETECCAO = {
    "type": "object",
    "properties": {
        "partes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "nome": {"type": "string"},
                    "animacoes": {"type": "array", "items": {"type": "string", "enum": list(ANIMACOES)}},
                    "caixa": {"type": "array", "items": {"type": "number"}},
                    "pivo": {"type": "array", "items": {"type": "number"}},
                    "direcao": {"type": "string", "enum": ["", "direita", "esquerda", "cima", "baixo", "horario",
                                                          "antihorario"]},
                    "observacao": {"type": "string"},
                },
                "required": ["nome", "animacoes", "caixa", "pivo", "direcao", "observacao"],
                "additionalProperties": False,
            },
        },
        "nao_encontrados": {"type": "array", "items": {"type": "string"}},
        "camera": {"type": "string", "enum": list(CAMERAS)},
    },
    "required": ["partes", "nao_encontrados", "camera"],
    "additionalProperties": False,
}

SISTEMA_DETECCAO = f"""Você localiza partes de ilustrações 2D (estilo desenho animado chapado) para um programa \
que anima cada parte automaticamente. Você recebe a imagem e a lista de elementos que o usuário quer animar.

Para cada elemento, devolva:
- caixa: [x0, y0, x1, y1] em pixels da imagem recebida (origem no canto superior esquerdo, x para a direita, \
y para baixo). A caixa deve conter o elemento INTEIRO, incluindo o contorno preto, e o mínimo possível de outras \
coisas. Seja preciso: o recorte é feito a partir dessa caixa.
- pivo: [x, y] ponto de articulação/rotação, também em pixels.
- animacoes: as que o usuário pediu para aquele elemento; se ele não disse, escolha a mais natural do catálogo.
- direcao: só para "deslizar" (direita, esquerda, cima, baixo) ou "girar" (horario, antihorario); senão "".
- observacao: uma frase curta se algo merecer atenção (ou "").

Regras de caixa e pivô:
- Olhos: UMA entrada por olho ("olho esquerdo" e "olho direito", do ponto de vista de quem vê a imagem), caixa \
justa em volta de cada olho. Pivô = centro do olho.
- Boca: só a boca, caixa justa. Pivô = centro.
- Braço: do ombro até a ponta dos dedos, incluindo a mão. Pivô no OMBRO (onde o braço encosta no corpo).
- Mão sozinha: pivô no pulso. Perna: pivô no quadril. Cabeça: pivô no pescoço. Rabo: pivô na base do rabo.
- Árvore, planta, placa fincada: pivô na base. Placa/lustre pendurado: pivô no ponto de onde pende.
- Sol, engrenagem, roda, ventilador, moeda, ícones e o resto: pivô no centro do objeto.
- Personagem inteiro (respirar): caixa do corpo todo, pivô nos pés.
- Tela de computador/celular (codigo): caixa só da área da tela, sem a moldura.
- Se o elemento aparece várias vezes, escolha a ocorrência principal (maior/mais central), a não ser que o \
pedido diga "todos"/"todas" — aí devolva uma entrada para cada.
- Se o elemento não existir na imagem, ponha o nome em nao_encontrados e não invente caixa.

Sugira também um movimento de câmera que combine com a cena.

Catálogo de animações:
{texto_catalogo()}

Movimentos de câmera:
{texto_cameras()}
"""


def _imagem_para_envio(rgb: np.ndarray) -> tuple[np.ndarray, float]:
    altura, largura = rgb.shape[:2]
    fator = min(1.0, LADO_MAXIMO_ENVIO / max(largura, altura))
    if fator < 1.0:
        rgb = cv2.resize(rgb, (int(round(largura * fator)), int(round(altura * fator))), interpolation=cv2.INTER_AREA)
    return rgb, fator


def _parte_da_resposta(item: dict, fator: float, largura: int, altura: int) -> Parte | None:
    caixa = item.get("caixa") or []
    if len(caixa) != 4 or not item.get("animacoes"):
        return None
    x0, y0, x1, y1 = (float(v) / fator for v in caixa)
    x0, x1 = sorted((float(np.clip(x0, 0, largura)), float(np.clip(x1, 0, largura))))
    y0, y1 = sorted((float(np.clip(y0, 0, altura)), float(np.clip(y1, 0, altura))))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    animacoes = [a for a in item["animacoes"] if a in ANIMACOES]
    pivo = None
    if len(item.get("pivo") or []) == 2:
        px, py = (float(v) / fator for v in item["pivo"])
        folga_x, folga_y = 0.35 * (x1 - x0) + 4, 0.35 * (y1 - y0) + 4
        if any(ANIMACOES[a].pivo == "manual" or a == "balancar" for a in animacoes):
            # articulação: pode ficar na borda da caixa, mas não longe dela
            px = float(np.clip(px, x0 - folga_x, x1 + folga_x))
            py = float(np.clip(py, y0 - folga_y, y1 + folga_y))
            pivo = (px, py)
        elif x0 <= px <= x1 and y0 <= py <= y1:
            pivo = (px, py)
    mascara = "auto"
    if all(ANIMACOES[a].mascara == "caixa" for a in animacoes):
        mascara = "caixa"
    return Parte(
        nome=str(item.get("nome") or "parte").strip(),
        animacoes=animacoes,
        caixa=(x0, y0, x1, y1),
        pivo=pivo,
        mascara=mascara,
        direcao=str(item.get("direcao") or ""),
    )


def detectar_partes(ia: ClienteIA, imagem: str | Path, pedido: str, contexto: str = "",
                    rgb: np.ndarray | None = None) -> tuple[list[Parte], list[str], str]:
    """Pergunta à IA onde estão os elementos. Retorna (partes, não encontrados, câmera sugerida)."""
    original = rgb if rgb is not None else carregar_rgb(imagem)
    altura, largura = original.shape[:2]
    envio, fator = _imagem_para_envio(original)
    itens = interpretar_pedido(pedido)
    lista = "\n".join(f"- {item.texto()}" for item in itens) or f"- {pedido}"
    texto = (f"A imagem tem {envio.shape[1]}x{envio.shape[0]} pixels.\n\n"
             f"Pedido original do usuário: {pedido}\n\nElementos para animar:\n{lista}")
    if contexto:
        texto += f"\n\nContexto da cena (do roteiro): {contexto}"
    resposta = ia.gerar_json(
        tarefa="detectar", sistema=SISTEMA_DETECCAO, conteudo=[bloco_imagem(envio), bloco_texto(texto)],
        schema=SCHEMA_DETECCAO, esforco="medium", max_tokens=16000, visao=True,
        mensagem=f"Localizando {', '.join(i.elemento for i in itens) or 'partes'} na imagem",
    )
    partes = [p for p in (_parte_da_resposta(item, fator, largura, altura) for item in resposta["partes"]) if p]
    return partes, list(resposta.get("nao_encontrados", [])), resposta.get("camera") or "zoom_in"


def partes_provisorias(pedido: str | list[ItemPedido], largura: int, altura: int) -> list[Parte]:
    """Sem IA: caixas enfileiradas no meio da imagem para ajustar no editor."""
    itens = interpretar_pedido(pedido) if isinstance(pedido, str) else pedido
    partes = []
    lado = 0.16 * min(largura, altura)
    for i, item in enumerate(itens):
        colunas = max(1, min(len(itens), 5))
        cx = largura * (i % colunas + 1) / (colunas + 1)
        cy = altura * (0.35 + 0.3 * (i // colunas))
        animacoes = item.animacoes_ou_padrao()
        mascara = "caixa" if all(ANIMACOES[a].mascara == "caixa" for a in animacoes) else "auto"
        partes.append(Parte(nome=item.elemento, animacoes=animacoes,
                            caixa=(cx - lado / 2, cy - lado / 2, cx + lado / 2, cy + lado / 2), mascara=mascara))
    return partes


def nova_spec(imagem: str | Path, partes: list[Parte], duracao: float, camera: str = "zoom_in",
              cena: int | None = None, caminho_relativo: str | None = None) -> SpecCena:
    original = carregar_rgb(imagem)
    altura, largura = original.shape[:2]
    return SpecCena(imagem=caminho_relativo or str(imagem), largura=largura, altura=altura, duracao=duracao,
                    camera=Camera(movimento=camera), partes=partes, cena=cena)
