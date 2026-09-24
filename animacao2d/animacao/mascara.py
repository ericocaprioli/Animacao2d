"""Recorte das partes (máscaras) e preenchimento do fundo atrás delas.

A máscara "auto" usa GrabCut dentro da caixa: funciona muito bem em
ilustrações chapadas com contorno preto (o estilo dos prompts gerados).
Se o recorte automático falhar, cai para elipse/caixa.
"""

from __future__ import annotations

import cv2
import numpy as np

Caixa = tuple[int, int, int, int]


def caixa_inteira(caixa, largura: int, altura: int) -> Caixa:
    """Arredonda e limita a caixa à imagem, garantindo pelo menos 2x2 px."""
    x0, y0, x1, y1 = caixa
    x0 = int(np.clip(np.floor(min(x0, x1)), 0, largura - 2))
    y0 = int(np.clip(np.floor(min(y0, y1)), 0, altura - 2))
    x1 = int(np.clip(np.ceil(max(x0 + 2, max(caixa[0], caixa[2]))), x0 + 2, largura))
    y1 = int(np.clip(np.ceil(max(y0 + 2, max(caixa[1], caixa[3]))), y0 + 2, altura))
    return x0, y0, x1, y1


def expandir(caixa: Caixa, fracao: float, largura: int, altura: int, minimo: int = 0) -> Caixa:
    x0, y0, x1, y1 = caixa
    mx = max(minimo, int(round((x1 - x0) * fracao)))
    my = max(minimo, int(round((y1 - y0) * fracao)))
    return max(0, x0 - mx), max(0, y0 - my), min(largura, x1 + mx), min(altura, y1 + my)


def _suavizar(mascara: np.ndarray, raio: float) -> np.ndarray:
    m = mascara.astype(np.float32)
    if m.max() > 1.0:
        m /= 255.0
    if raio > 0:
        m = cv2.GaussianBlur(m, (0, 0), raio)
    return np.clip(m, 0.0, 1.0)


def mascara_retangulo(largura: int, altura: int, caixa: Caixa, suave: float = 1.0) -> np.ndarray:
    m = np.zeros((altura, largura), np.uint8)
    x0, y0, x1, y1 = caixa
    m[y0:y1, x0:x1] = 255
    return _suavizar(m, suave)


def mascara_elipse(largura: int, altura: int, caixa: Caixa, suave: float = 1.0) -> np.ndarray:
    m = np.zeros((altura, largura), np.uint8)
    x0, y0, x1, y1 = caixa
    centro = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
    eixos = (max(1.0, (x1 - x0) / 2.0), max(1.0, (y1 - y0) / 2.0))
    cv2.ellipse(m, (centro, (eixos[0] * 2, eixos[1] * 2), 0.0), 255, -1, cv2.LINE_AA)
    return _suavizar(m, suave)


def _preencher_buracos(binaria: np.ndarray) -> np.ndarray:
    """Preenche buracos internos (ex.: o branco dos olhos dentro da cabeça)."""
    borda = cv2.copyMakeBorder(binaria, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    inundacao = borda.copy()
    controle = np.zeros((borda.shape[0] + 2, borda.shape[1] + 2), np.uint8)
    cv2.floodFill(inundacao, controle, (0, 0), 255)
    buracos = inundacao[1:-1, 1:-1] == 0
    saida = binaria.copy()
    saida[buracos] = 255
    return saida


def _grabcut(roi: np.ndarray, caixa_roi: Caixa) -> np.ndarray | None:
    """Frente segundo o GrabCut (uint8 0/255 no tamanho do roi) ou None."""
    x0, y0, x1, y1 = caixa_roi
    bw, bh = x1 - x0, y1 - y0
    ex, ey = max(2, int(bw * 0.06)), max(2, int(bh * 0.06))
    rx0, ry0 = max(1, x0 - ex), max(1, y0 - ey)
    rx1, ry1 = min(roi.shape[1] - 1, x1 + ex), min(roi.shape[0] - 1, y1 + ey)
    if rx1 - rx0 < 4 or ry1 - ry0 < 4 or (rx1 - rx0) * (ry1 - ry0) >= 0.97 * roi.shape[0] * roi.shape[1]:
        return None
    rotulos = np.zeros(roi.shape[:2], np.uint8)
    fundo_modelo = np.zeros((1, 65), np.float64)
    frente_modelo = np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(roi, rotulos, (rx0, ry0, rx1 - rx0, ry1 - ry0), fundo_modelo, frente_modelo, 5,
                    cv2.GC_INIT_WITH_RECT)
    except cv2.error:
        return None
    frente = np.where((rotulos == cv2.GC_FGD) | (rotulos == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    frente = cv2.morphologyEx(frente, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    frente = cv2.morphologyEx(frente, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    # mantém só os pedaços que estão (majoritariamente) dentro da caixa pedida
    dentro = np.zeros_like(frente)
    dentro[y0:y1, x0:x1] = 1
    n, rot, stats, _ = cv2.connectedComponentsWithStats(frente, connectivity=8)
    escolhida = np.zeros_like(frente)
    area_minima = max(12.0, 0.002 * bw * bh)
    for i in range(1, n):
        componente = rot == i
        area = stats[i, cv2.CC_STAT_AREA]
        sobreposicao = float(dentro[componente].sum())
        if sobreposicao >= 0.5 * area and sobreposicao >= area_minima:
            escolhida[componente] = 255
    return escolhida


def _distancia_cores(pixels: np.ndarray, cores: np.ndarray) -> np.ndarray:
    """Menor distância (RGB) de cada pixel até alguma das cores dadas."""
    plano = pixels.reshape(-1, 1, 3).astype(np.float32)
    return np.min(np.linalg.norm(plano - cores[None, :, :].astype(np.float32), axis=2), axis=1)


def _cores_de_fundo(roi: np.ndarray, rotulos: np.ndarray) -> np.ndarray:
    """Cores do fundo "de verdade": regiões que envolvem a peça por (quase) todos os lados.

    Não basta pegar tudo que encosta na borda do contexto: o tronco verde encosta
    na borda do contexto do braço, mas a manga verde não é fundo. O céu, que
    aparece em 3 ou 4 lados da moldura, é.
    """
    lados = [rotulos[:2, :], rotulos[-2:, :], rotulos[:, :2], rotulos[:, -2:]]
    presenca: dict[int, int] = {}
    contato: dict[int, int] = {}
    for lado in lados:
        valores, contagens = np.unique(lado[lado > 0], return_counts=True)
        for valor, quantidade in zip(valores.tolist(), contagens.tolist()):
            presenca[valor] = presenca.get(valor, 0) + 1
            contato[valor] = contato.get(valor, 0) + quantidade
    escolhidos = [r for r, n in presenca.items() if n >= 3]
    if not escolhidos and contato:
        escolhidos = [max(contato, key=contato.get)]
    escolhidos = sorted(escolhidos, key=lambda r: -contato[r])[:8]
    cores = [np.median(roi[rotulos == r].reshape(-1, 3).astype(np.float32), axis=0) for r in escolhidos]
    if not cores:  # tudo é contorno na moldura: usa a cor mediana das bordas
        cores = [np.median(np.concatenate([roi[:2].reshape(-1, 3), roi[-2:].reshape(-1, 3)]).astype(np.float32), axis=0)]
    return np.array(cores, np.float32)


def _regioes_desenhadas(roi: np.ndarray, caixa_roi: Caixa, frente: np.ndarray | None) -> tuple[np.ndarray, np.ndarray]:
    """Regiões fechadas por contorno que ficam quase inteiras dentro da caixa.

    Em ilustrações com contorno, cada área de cor (mão, manga, raio do sol) é
    uma região. Pegar só as que cabem na caixa evita levar junto pedaços de
    vizinhos que apenas encostam nela (ex.: a cabeça ao lado do braço).
    Retorna (máscara uint8, cores do fundo).
    """
    x0, y0, x1, y1 = caixa_roi
    cinza = cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY)
    bordas = cv2.Canny(cv2.GaussianBlur(cinza, (3, 3), 0), 40, 110)
    separadores = cv2.dilate(bordas, np.ones((2, 2), np.uint8))
    n, rot, stats, _ = cv2.connectedComponentsWithStats((separadores == 0).astype(np.uint8), connectivity=4)
    altura, largura = roi.shape[:2]
    dentro = np.zeros((altura, largura), bool)
    dentro[y0:y1, x0:x1] = True
    fundo = _cores_de_fundo(roi, rot)
    escolhida = np.zeros((altura, largura), np.uint8)
    area_minima = max(8.0, 0.0008 * (x1 - x0) * (y1 - y0))
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < area_minima or x == 0 or y == 0 or x + w >= largura or y + h >= altura:
            continue  # encosta na borda do contexto: é maior que a peça
        if x >= x1 or y >= y1 or x + w <= x0 or y + h <= y0:
            continue
        componente = rot == i
        if dentro[componente].sum() < 0.6 * area:
            continue
        cor = np.median(roi[componente].astype(np.float32), axis=0)
        parece_fundo = float(_distancia_cores(cor[None, :], fundo)[0]) < 40
        if parece_fundo and (frente is None or (frente[componente] > 0).sum() < 0.6 * area):
            continue  # ex.: o pedaço de céu entre o braço e a cabeça
        escolhida[componente] = 255
    # detalhes finos (raios do sol, faíscas): pedaços com cor diferente do fundo
    # que cabem inteiros na caixa, mesmo que os contornos os "engulam"
    diferente = (_distancia_cores(roi, fundo).reshape(altura, largura) > 45).astype(np.uint8)
    n2, rot2, stats2, _ = cv2.connectedComponentsWithStats(diferente, connectivity=8)
    for i in range(1, n2):
        x, y, w, h, area = stats2[i]
        if area < max(6.0, 0.0003 * (x1 - x0) * (y1 - y0)):
            continue
        if x == 0 or y == 0 or x + w >= largura or y + h >= altura:
            continue
        componente = rot2 == i
        if dentro[componente].sum() >= 0.6 * area:
            escolhida[componente] = 255
    if escolhida.any():
        # cresce só para dentro dos traços escuros (o contorno preto da peça)
        escuros = ((cinza < 110) | (separadores > 0)).astype(np.uint8) * 255
        espessura = max(3, int(round(min(roi.shape[:2]) / 60)))
        for _ in range(espessura):
            crescida = cv2.dilate(escolhida, np.ones((3, 3), np.uint8))
            escolhida = np.maximum(escolhida, cv2.bitwise_and(crescida, escuros))
    return escolhida, fundo


def _capsula(forma: tuple[int, int], pivo: tuple[float, float], ponta: tuple[float, float], raio: float) -> np.ndarray:
    m = np.zeros(forma, np.uint8)
    cv2.line(m, (int(pivo[0]), int(pivo[1])), (int(ponta[0]), int(ponta[1])), 255, max(1, int(2 * raio)), cv2.LINE_AA)
    cv2.circle(m, (int(pivo[0]), int(pivo[1])), int(raio), 255, -1, cv2.LINE_AA)
    cv2.circle(m, (int(ponta[0]), int(ponta[1])), int(raio), 255, -1, cv2.LINE_AA)
    return m


def _limitar_membro(mascara: np.ndarray, pivo: tuple[float, float]) -> np.ndarray:
    """Para braços/pernas: fica só com o 'tubo' que sai do pivô até a ponta."""
    ys, xs = np.nonzero(mascara)
    if len(xs) < 10:
        return mascara
    distancias = np.hypot(xs - pivo[0], ys - pivo[1])
    k = int(np.argmax(distancias))
    ponta = (float(xs[k]), float(ys[k]))
    comprimento = float(distancias[k])
    if comprimento < 8:
        return mascara
    distancia_fundo = cv2.distanceTransform((mascara > 0).astype(np.uint8), cv2.DIST_L2, 3)
    amostras = []
    for f in np.linspace(0.3, 0.85, 12):
        px = int(round(pivo[0] + f * (ponta[0] - pivo[0])))
        py = int(round(pivo[1] + f * (ponta[1] - pivo[1])))
        if 0 <= py < mascara.shape[0] and 0 <= px < mascara.shape[1] and distancia_fundo[py, px] > 0:
            amostras.append(distancia_fundo[py, px])
    if len(amostras) < 4:
        return mascara
    raio = float(np.percentile(amostras, 75)) * 1.45 + 3
    raio = min(raio, 0.45 * comprimento)
    return cv2.bitwise_and(mascara, _capsula(mascara.shape, pivo, ponta, raio))


def mascara_auto(img: np.ndarray, caixa: Caixa, pivo_membro: tuple[float, float] | None = None) -> np.ndarray | None:
    """Recorte automático. Retorna máscara float32 (0..1) do tamanho da imagem ou None.

    `pivo_membro`: para partes que giram presas numa ponta (braço, perna), o
    ponto de articulação; ajuda a descartar vizinhos quando o recorte vaza.
    """
    altura, largura = img.shape[:2]
    x0, y0, x1, y1 = caixa
    bw, bh = x1 - x0, y1 - y0
    if bw < 6 or bh < 6:
        return None
    # região de contexto: dá ao GrabCut exemplos de fundo em volta da caixa
    cx0, cy0, cx1, cy1 = expandir(caixa, 0.5, largura, altura, minimo=16)
    roi = np.ascontiguousarray(img[cy0:cy1, cx0:cx1])
    caixa_roi = (x0 - cx0, y0 - cy0, x1 - cx0, y1 - cy0)
    frente = _grabcut(roi, caixa_roi)
    regioes, fundo = _regioes_desenhadas(roi, caixa_roi, frente)
    area_caixa = float(bw * bh)
    area_frente = float((frente > 0).sum()) if frente is not None else 0.0
    area_regioes = float((regioes > 0).sum())
    # o GrabCut achou "peça" que as regiões não pegaram? (ex.: manga emendada no tronco)
    extra_de_peca = 0.0
    if frente is not None and area_regioes:
        folga = cv2.dilate(regioes, np.ones((7, 7), np.uint8))
        extra = (frente > 0) & (folga == 0)
        if extra.any():
            extra_de_peca = float((_distancia_cores(roi[extra], fundo) > 45).sum())
    if area_regioes >= 0.04 * area_caixa and (frente is None or extra_de_peca <= 0.6 * area_regioes):
        escolhida = regioes
    elif frente is not None and 0.04 * area_caixa <= area_frente <= 1.5 * area_caixa:
        escolhida = frente
        if pivo_membro is not None:
            escolhida = _limitar_membro(escolhida, (pivo_membro[0] - cx0, pivo_membro[1] - cy0))
    else:
        return None
    escolhida = _preencher_buracos(escolhida)
    completa = np.zeros((altura, largura), np.uint8)
    completa[cy0:cy1, cx0:cx1] = escolhida
    dilata = max(1, int(round(min(largura, altura) / 720)))
    completa = cv2.dilate(completa, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * dilata + 1, 2 * dilata + 1)))
    return _suavizar(completa, 0.8)


def calcular_mascara(img: np.ndarray, caixa: Caixa, modo: str, preferencia_redonda: bool = False,
                     pivo_membro: tuple[float, float] | None = None) -> tuple[np.ndarray, str]:
    """Retorna (máscara float32 0..1, modo efetivamente usado)."""
    altura, largura = img.shape[:2]
    if modo == "auto":
        m = mascara_auto(img, caixa, pivo_membro)
        if m is not None:
            return m, "auto"
        modo = "elipse" if preferencia_redonda else "caixa"
    if modo == "elipse":
        return mascara_elipse(largura, altura, caixa), "elipse"
    return mascara_retangulo(largura, altura, caixa), "caixa"


def bbox_mascara(mascara: np.ndarray, limiar: float = 0.02) -> Caixa | None:
    ys, xs = np.nonzero(mascara > limiar)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def remover_partes(img: np.ndarray, uniao: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Imagem com as partes móveis apagadas (buraco preenchido pelo entorno) e o buraco usado."""
    binaria = (uniao > 0.03).astype(np.uint8) * 255
    if not binaria.any():
        return img.copy(), binaria
    altura, largura = img.shape[:2]
    raio = max(2, int(round(min(largura, altura) / 360)))
    binaria = cv2.dilate(binaria, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * raio + 1, 2 * raio + 1)))
    saida = img.copy()
    n, rotulos, stats, _ = cv2.connectedComponentsWithStats(binaria, connectivity=8)
    for i in range(1, n):  # cada buraco é preenchido só com o seu entorno
        x, y, w, h, _ = stats[i]
        x0, y0, x1, y1 = expandir((x, y, x + w, y + h), 0.0, largura, altura, minimo=12)
        buraco = np.where(rotulos[y0:y1, x0:x1] == i, 255, 0).astype(np.uint8)
        saida[y0:y1, x0:x1] = preencher_suave(np.ascontiguousarray(saida[y0:y1, x0:x1]), buraco)
    return saida, binaria


def preencher_suave(img: np.ndarray, buraco: np.ndarray) -> np.ndarray:
    """Preenche o buraco interpolando as cores da borda (pirâmide "push-pull").

    Em fundos chapados o resultado é exatamente a cor do fundo; em degradês,
    uma transição suave. Fica melhor que o inpaint clássico nesse estilo.
    """
    # só o anel logo em volta do buraco serve de referência (não mistura cores distantes)
    anel = cv2.dilate(buraco, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))) & ~buraco
    valido = (anel > 0).astype(np.float32)
    cor = img.astype(np.float32)
    niveis = []
    soma, peso = cor * valido[..., None], valido
    while min(soma.shape[:2]) > 2:
        niveis.append((soma, peso))
        tamanho = (max(1, soma.shape[1] // 2), max(1, soma.shape[0] // 2))
        soma = cv2.resize(soma, tamanho, interpolation=cv2.INTER_AREA)
        peso = cv2.resize(peso, tamanho, interpolation=cv2.INTER_AREA)
    estimativa = soma / np.maximum(peso, 1e-6)[..., None]
    for soma_n, peso_n in reversed(niveis):
        acima = cv2.resize(estimativa, (soma_n.shape[1], soma_n.shape[0]), interpolation=cv2.INTER_LINEAR)
        # soma_n já é "cor x peso": completa o que falta com o nível mais grosso
        estimativa = soma_n + (1.0 - np.clip(peso_n, 0, 1))[..., None] * acima
    # suaviza só dentro do buraco (tira o "serrilhado" da pirâmide)
    suave = cv2.GaussianBlur(estimativa, (0, 0), 1.5)
    dentro = (buraco > 0).astype(np.float32)[..., None]
    resultado = cor * (1.0 - dentro) + suave * dentro
    return np.clip(resultado + 0.5, 0, 255).astype(np.uint8)


def cor_ao_redor(img: np.ndarray, caixa: Caixa, largura_anel: int = 3) -> np.ndarray:
    """Cor predominante logo em volta da caixa (ex.: a pele em volta do olho)."""
    altura, largura = img.shape[:2]
    x0, y0, x1, y1 = caixa
    ex0, ey0, ex1, ey1 = max(0, x0 - largura_anel), max(0, y0 - largura_anel), min(largura, x1 + largura_anel), min(altura, y1 + largura_anel)
    regiao = img[ey0:ey1, ex0:ex1].reshape(-1, 3)
    anel = np.ones((ey1 - ey0, ex1 - ex0), bool)
    ix0, iy0 = x0 - ex0 + largura_anel // 2 + 1, y0 - ey0 + largura_anel // 2 + 1
    ix1, iy1 = x1 - ex0 - largura_anel // 2 - 1, y1 - ey0 - largura_anel // 2 - 1
    if ix1 > ix0 and iy1 > iy0:
        anel[iy0:iy1, ix0:ix1] = False
    pixels = regiao[anel.reshape(-1)]
    if len(pixels) == 0:
        pixels = regiao
    luminancia = pixels.astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
    claros = pixels[luminancia > 70]
    if len(claros) >= max(8, 0.3 * len(pixels)):
        pixels = claros
    # moda aproximada: mediana dos pixels mais parecidos com a mediana geral
    mediana = np.median(pixels.astype(np.float32), axis=0)
    distancia = np.linalg.norm(pixels.astype(np.float32) - mediana, axis=1)
    proximos = pixels[distancia <= np.percentile(distancia, 60)]
    return np.median(proximos.astype(np.float32), axis=0)
