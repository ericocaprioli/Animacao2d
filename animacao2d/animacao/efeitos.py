"""Efeitos de cada parte: movimentos (pose) e pinturas no lugar (piscar, falar...).

Todos os efeitos são determinísticos: renderizar de novo dá o mesmo resultado.
Coordenadas aqui já estão na resolução de trabalho do renderizador.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from animacao2d.animacao.catalogo import ANIMACOES
from animacao2d.animacao.mascara import Caixa, caixa_inteira, cor_ao_redor, expandir
from animacao2d.animacao.spec import Parte

TAU = 2.0 * math.pi


@dataclass
class Pose:
    dx: float = 0.0
    dy: float = 0.0
    angulo: float = 0.0  # graus, positivo = sentido horário na tela
    macio: bool = False  # rotação "de articulação": perto do pivô gira menos
    sx: float = 1.0
    sy: float = 1.0
    ancora: tuple[float, float] | None = None
    alfa: float = 1.0

    def identidade(self) -> bool:
        return (abs(self.dx) < 1e-3 and abs(self.dy) < 1e-3 and abs(self.angulo) < 1e-3
                and abs(self.sx - 1) < 1e-4 and abs(self.sy - 1) < 1e-4)


def _suave01(x: np.ndarray | float) -> np.ndarray | float:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def _elastico(u: float, forca: float) -> float:
    """easeOutBack: passa um pouco do tamanho final e volta."""
    c1 = 1.70158 * forca
    c3 = c1 + 1.0
    return 1.0 + c3 * (u - 1.0) ** 3 + c1 * (u - 1.0) ** 2


class _Ruido:
    """Ruído suave e determinístico no intervalo aproximado [-1, 1]."""

    def __init__(self, semente: int, frequencia: float):
        rng = np.random.default_rng(semente)
        self.freqs = frequencia * rng.uniform(0.6, 1.6, 3)
        self.fases = rng.uniform(0, TAU, 3)
        self.pesos = np.array([0.55, 0.3, 0.15])

    def __call__(self, t: float) -> float:
        return float(np.sum(self.pesos * np.sin(TAU * self.freqs * t + self.fases)))


def _paleta_codigo(fundo_escuro: bool) -> list[tuple[int, int, int]]:
    if fundo_escuro:
        return [(126, 231, 135), (121, 192, 255), (255, 166, 87), (210, 168, 255), (230, 237, 243)]
    return [(26, 127, 55), (9, 105, 218), (188, 76, 0), (130, 80, 223), (87, 96, 106)]


def _grupos_de_pixels(diferentes: np.ndarray, area_minima: float) -> list[Caixa]:
    """Componentes conectados -> caixas, juntando pedaços vizinhos (pupila + contorno)."""
    n, _, stats, _ = cv2.connectedComponentsWithStats(diferentes.astype(np.uint8), connectivity=8)
    caixas = []
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= area_minima:
            x, y, w, h = stats[i, :4]
            caixas.append([x, y, x + w, y + h])
    mudou = True
    while mudou and len(caixas) > 1:
        mudou = False
        for i in range(len(caixas)):
            for j in range(i + 1, len(caixas)):
                a, b = caixas[i], caixas[j]
                folga = 0.25 * max(a[2] - a[0], b[2] - b[0], a[3] - a[1], b[3] - b[1])
                if a[0] - folga <= b[2] and b[0] - folga <= a[2] and a[1] - folga <= b[3] and b[1] - folga <= a[3]:
                    caixas[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    caixas.pop(j)
                    mudou = True
                    break
            if mudou:
                break
    return [tuple(int(v) for v in c) for c in caixas]  # type: ignore[misc]


class ParteAnimada:
    """Uma parte da cena pronta para ser animada quadro a quadro."""

    def __init__(self, parte: Parte, img: np.ndarray, escala: float, duracao: float, semente: int):
        altura, largura = img.shape[:2]
        self.parte = parte
        self.nome = parte.nome
        self.largura_img, self.altura_img = largura, altura
        self.caixa = caixa_inteira([v * escala for v in parte.caixa], largura, altura)
        px, py = parte.pivo_efetivo()
        self.pivo = (px * escala, py * escala)
        self.i = float(parte.intensidade)
        self.v = max(0.05, float(parte.velocidade))
        self.atraso = float(parte.atraso)
        self.duracao = duracao
        self.semente = semente
        self.movimentos = [a for a in parte.animacoes if ANIMACOES[a].categoria == "movimento"]
        self.pinturas = [a for a in parte.animacoes if ANIMACOES[a].categoria == "pintura"]
        self.mascara: np.ndarray | None = None  # preenchida pelo renderizador
        self.modo_mascara = parte.mascara
        self.envelope_boca: np.ndarray | None = None  # abertura da boca por quadro (áudio)
        self.fps = 30.0
        rng = np.random.default_rng(semente)
        self.fase = float(rng.uniform(0, TAU))
        self._ruidos = [_Ruido(semente * 7 + k, 1.0) for k in range(3)]
        self._dados: dict[str, object] = {}
        self._preparar(img)

    # ------------------------------------------------------------ preparo

    @property
    def precisa_mascara(self) -> bool:
        return bool(self.movimentos) or "brilhar" in self.pinturas

    @property
    def redonda(self) -> bool:
        return any(a in ("girar", "pulsar") for a in self.movimentos)

    def _preparar(self, img: np.ndarray) -> None:
        if "piscar" in self.pinturas:
            self._dados["piscar"] = self._preparar_olhos(img)
        if "falar" in self.pinturas:
            self._dados["falar"] = self._preparar_boca(img)
        if "ondular" in self.pinturas:
            self._dados["ondular"] = self._preparar_onda()
        if "codigo" in self.pinturas:
            self._dados["codigo"] = self._preparar_codigo(img)

    def preparar_brilho(self, img: np.ndarray) -> None:
        """Chamado depois que a máscara existe."""
        if "brilhar" not in self.pinturas or self.mascara is None:
            return
        x0, y0, x1, y1 = self.caixa
        raio = 0.18 * max(x1 - x0, y1 - y0) + 2
        rx0, ry0, rx1, ry1 = expandir(self.caixa, 0.0, self.largura_img, self.altura_img, minimo=int(raio * 2.5))
        m = self.mascara[ry0:ry1, rx0:rx1]
        halo = cv2.GaussianBlur(m, (0, 0), raio)
        halo = np.clip(halo / max(1e-6, float(halo.max())) * 1.2, 0, 1)
        dentro = m > 0.5
        media = img[ry0:ry1, rx0:rx1][dentro].mean(axis=0) if dentro.any() else np.array([255, 230, 150])
        cor = 0.45 * media + 0.55 * np.array([255.0, 244.0, 190.0])
        self._dados["brilhar"] = ((rx0, ry0, rx1, ry1), halo.astype(np.float32), m.astype(np.float32),
                                  cor.astype(np.float32))

    def _preparar_olhos(self, img: np.ndarray):
        altura, largura = img.shape[:2]
        busca = expandir(self.caixa, 0.15, largura, altura, minimo=1)
        pele = cor_ao_redor(img, busca, largura_anel=max(2, (busca[2] - busca[0]) // 10))
        x0, y0, x1, y1 = busca
        regiao = img[y0:y1, x0:x1].astype(np.float32)
        diferenca = np.linalg.norm(regiao - pele, axis=2) > 48
        area_minima = max(3.0, 0.004 * diferenca.size)
        olhos = []
        for gx0, gy0, gx1, gy1 in _grupos_de_pixels(diferenca, area_minima):
            if (gx1 - gx0) * (gy1 - gy0) < 0.9 * diferenca.size:
                pixels = regiao[gy0:gy1, gx0:gx1][diferenca[gy0:gy1, gx0:gx1]]
                escuro = pixels[np.argmin(pixels @ np.array([0.299, 0.587, 0.114], np.float32))]
                olhos.append(((gx0 + x0, gy0 + y0, gx1 + x0, gy1 + y0), tuple(float(c) for c in escuro)))
        if not olhos:  # não achou nada distinto: pisca a caixa inteira
            olhos = [(self.caixa, (40.0, 34.0, 34.0))]
        rng = np.random.default_rng(self.semente + 101)
        piscadas = []
        t = 0.4 + float(rng.uniform(0.0, 1.2))
        while t < self.duracao + 1.0:
            piscadas.append(t)
            if rng.random() < 0.2:
                piscadas.append(t + 0.3)
            t += float(rng.uniform(2.2, 4.2)) / self.v
        return olhos, tuple(float(c) for c in pele), piscadas

    def _preparar_boca(self, img: np.ndarray):
        altura, largura = img.shape[:2]
        busca = expandir(self.caixa, 0.12, largura, altura, minimo=1)
        pele = cor_ao_redor(img, busca, largura_anel=max(2, (busca[2] - busca[0]) // 10))
        x0, y0, x1, y1 = busca
        regiao = img[y0:y1, x0:x1].astype(np.float32)
        diferenca = np.linalg.norm(regiao - pele, axis=2) > 48
        ys, xs = np.nonzero(diferenca)
        if len(xs) >= 4:
            mx0, mx1 = xs.min() + x0, xs.max() + 1 + x0
            my0, my1 = ys.min() + y0, ys.max() + 1 + y0
            pixels = regiao[diferenca]
            escuro = pixels[np.argmin(pixels @ np.array([0.299, 0.587, 0.114], np.float32))]
        else:
            mx0, my0, mx1, my1 = self.caixa
            escuro = np.array([45.0, 30.0, 30.0])
        geometria = ((mx0 + mx1) / 2.0, (my0 + my1) / 2.0, float(mx1 - mx0), float(my1 - my0))
        return geometria, tuple(float(c) for c in pele), tuple(float(c) for c in escuro)

    def _preparar_onda(self):
        x0, y0, x1, y1 = self.caixa
        largura, altura = x1 - x0, y1 - y0
        xs = np.arange(x0, x1, dtype=np.float32)
        ys = np.arange(y0, y1, dtype=np.float32)
        gx, gy = np.meshgrid(xs, ys)
        borda_x = _suave01(np.minimum(gx - x0, x1 - 1 - gx) / max(1.0, 0.15 * largura))
        borda_y = _suave01(np.minimum(gy - y0, y1 - 1 - gy) / max(1.0, 0.15 * altura))
        peso = borda_x * borda_y
        if self.parte.pivo is not None:  # ex.: bandeira presa no mastro
            peso = peso * np.clip(np.abs(gx - self.pivo[0]) / max(1.0, largura), 0.0, 1.0)
        return gx, gy, peso.astype(np.float32)

    def _preparar_codigo(self, img: np.ndarray):
        cx0, cy0, cx1, cy1 = self.caixa
        margem_x, margem_y = int(round(0.08 * (cx1 - cx0))), int(round(0.08 * (cy1 - cy0)))
        x0, y0, x1, y1 = cx0 + margem_x, cy0 + margem_y, cx1 - margem_x, cy1 - margem_y
        regiao = img[y0:y1, x0:x1].reshape(-1, 3).astype(np.float32)
        fundo = np.median(regiao, axis=0)
        escuro = float(fundo @ np.array([0.299, 0.587, 0.114])) < 128
        altura_linha = float(np.clip((y1 - y0) / 8.5, 5, 42))
        largura_char = max(2.0, altura_linha * 0.5)
        visiveis = max(1, int((y1 - y0) // altura_linha))
        max_chars = max(4, int((x1 - x0) / largura_char) - 1)
        rng = np.random.default_rng(self.semente + 202)
        velocidade = 16.0 * self.v * max(0.2, self.i)
        total = velocidade * (self.duracao + 1.0) + max_chars * visiveis
        linhas = []  # cada linha: (recuo, [(inicio, tamanho, cor)], total_chars)
        paleta = _paleta_codigo(escuro)
        nivel, acumulado = 0, 0
        while acumulado < total:
            nivel = int(np.clip(nivel + rng.choice([-1, 0, 0, 1]), 0, 3))
            recuo = nivel * 2
            tokens, pos = [], recuo
            for _ in range(int(rng.integers(1, 5))):
                tamanho = int(rng.integers(2, 9))
                if pos + tamanho > max_chars:
                    break
                tokens.append((pos, tamanho, paleta[int(rng.integers(0, len(paleta)))]))
                pos += tamanho + 1
            if not tokens:
                nivel = 0
                continue
            linhas.append((recuo, tokens, pos))
            acumulado += pos
        return (x0, y0, x1, y1), fundo, altura_linha, largura_char, visiveis, linhas, velocidade

    # ------------------------------------------------------------ movimento

    def pose(self, t: float) -> Pose:
        p = Pose()
        x0, y0, x1, y1 = self.caixa
        centro = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
        tt = t - self.atraso
        i, v = self.i, self.v
        for nome in self.movimentos:
            if nome == "aparecer":
                if tt < 0:
                    p.alfa = 0.0
                    continue
                u = min(1.0, tt / (0.45 / v))
                s = max(1e-3, _elastico(u, max(0.2, i)))
                p.sx *= s
                p.sy *= s
                p.alfa *= min(1.0, u / 0.25)
                p.ancora = p.ancora or centro
                continue
            if tt <= 0:
                continue
            if nome == "acenar":
                p.angulo += 16.0 * i * math.sin(TAU * 1.25 * v * tt)
                p.macio = True
            elif nome == "balancar":
                p.angulo += 6.0 * i * math.sin(TAU * 0.45 * v * tt + self.fase)
                p.macio = True
            elif nome == "girar":
                sentido = -1.0 if self.parte.direcao == "antihorario" else 1.0
                p.angulo += sentido * 360.0 * 0.12 * v * max(0.1, i) * tt
            elif nome == "pulsar":
                s = 1.0 + 0.09 * i * (0.5 - 0.5 * math.cos(TAU * 1.1 * v * tt))
                p.sx *= s
                p.sy *= s
                p.ancora = p.ancora or centro
            elif nome == "flutuar":
                p.dy -= 0.022 * self.altura_img * i * math.sin(TAU * 0.35 * v * tt + self.fase)
                p.angulo += 1.2 * i * math.sin(TAU * 0.35 * v * tt + self.fase + 1.2)
            elif nome == "deslizar":
                distancia = 0.035 * self.largura_img * v * i * tt
                direcao = self.parte.direcao or "direita"
                if direcao == "esquerda":
                    p.dx -= distancia
                elif direcao == "cima":
                    p.dy -= distancia
                elif direcao == "baixo":
                    p.dy += distancia
                else:
                    p.dx += distancia
            elif nome == "tremer":
                amplitude = 0.005 * self.largura_img * i
                p.dx += amplitude * self._ruidos[0](tt * 11.0 * v)
                p.dy += amplitude * self._ruidos[1](tt * 13.0 * v)
                p.angulo += 1.5 * i * self._ruidos[2](tt * 9.0 * v)
            elif nome == "respirar":
                s = 0.5 - 0.5 * math.cos(TAU * 0.28 * v * tt + self.fase)
                p.sy *= 1.0 + 0.018 * i * s
                p.sx *= 1.0 + 0.006 * i * s
                p.ancora = p.ancora or ((x0 + x1) / 2.0, float(y1))
        return p

    # ------------------------------------------------------------ pinturas

    def pintar(self, quadro: np.ndarray, t: float, indice_quadro: int) -> None:
        for nome in self.pinturas:
            if nome == "piscar":
                self._pintar_piscada(quadro, t)
            elif nome == "falar":
                self._pintar_boca(quadro, t, indice_quadro)
            elif nome == "brilhar":
                self._pintar_brilho(quadro, t)
            elif nome == "ondular":
                self._pintar_onda(quadro, t)
            elif nome == "codigo":
                self._pintar_codigo(quadro, t)

    def _fechamento(self, t: float, piscadas: list[float]) -> float:
        fechar, fechado, abrir = 0.05, 0.07, 0.06
        valor = 0.0
        for inicio in piscadas:
            d = t - inicio
            if d < 0 or d > fechar + fechado + abrir:
                continue
            if d < fechar:
                valor = max(valor, d / fechar)
            elif d < fechar + fechado:
                valor = 1.0
            else:
                valor = max(valor, 1.0 - (d - fechar - fechado) / abrir)
        return valor

    def _pintar_piscada(self, quadro: np.ndarray, t: float) -> None:
        olhos, pele, piscadas = self._dados["piscar"]  # type: ignore[misc]
        c = self._fechamento(t - max(0.0, self.atraso), piscadas)
        if c <= 0.05:
            return
        altura, largura = quadro.shape[:2]
        for (ex0, ey0, ex1, ey1), escuro in olhos:
            w, h = ex1 - ex0, ey1 - ey0
            folga = max(1, int(round(0.15 * max(w, h)))) + 1
            px0, py0, px1, py1 = max(0, ex0 - folga - 2), max(0, ey0 - folga - 2), min(largura, ex1 + folga + 2), min(altura, ey1 + folga + 2)
            trecho = quadro[py0:py1, px0:px1].astype(np.float32)
            cx, cy = (ex0 + ex1) / 2.0 - px0, (ey0 + ey1) / 2.0 - py0
            palpebra = np.zeros(trecho.shape[:2], np.uint8)
            cv2.ellipse(palpebra, ((cx, cy), (w + 2 * folga, h + 2 * folga), 0.0), 255, -1, cv2.LINE_AA)
            limite = (ey0 - folga - py0) + c * (h + 2 * folga)
            linhas = np.arange(trecho.shape[0], dtype=np.float32)[:, None]
            corte = np.clip(limite - linhas + 0.5, 0.0, 1.0)
            alfa = (palpebra.astype(np.float32) / 255.0) * corte
            trecho = trecho * (1 - alfa[..., None]) + np.array(pele, np.float32) * alfa[..., None]
            if c >= 0.8:
                espessura = max(1, int(round(0.14 * max(w, h))))
                arco = np.ascontiguousarray(np.clip(trecho, 0, 255).astype(np.uint8))
                cv2.ellipse(arco, ((cx, cy + 0.1 * h), (w + folga * 0.6, max(2.0, 0.45 * h)), 0.0),
                            tuple(int(v) for v in escuro), espessura, cv2.LINE_AA)
                # usa só a metade de baixo do arco (olho fechado sorridente)
                metade = np.zeros(trecho.shape[:2], np.float32)
                metade[int(round(cy + 0.1 * h)):, :] = 1.0
                trecho = trecho * (1 - metade[..., None]) + arco.astype(np.float32) * metade[..., None]
            quadro[py0:py1, px0:px1] = np.clip(trecho + 0.5, 0, 255).astype(np.uint8)

    def _abertura_boca(self, t: float, indice_quadro: int) -> float:
        if self.envelope_boca is not None and len(self.envelope_boca):
            return float(self.envelope_boca[min(indice_quadro, len(self.envelope_boca) - 1)])
        tt = (t - self.atraso) * self.v
        if tt < 0:
            return 0.0
        f = self.fase
        silaba = (math.sin(TAU * 4.3 * tt + f) + 0.6 * math.sin(TAU * 6.7 * tt + 2 * f)
                  + 0.3 * math.sin(TAU * 10.1 * tt + 3 * f))
        abertura = np.clip(0.45 * silaba + 0.35, 0.0, 1.0)
        pausa = (tt / 2.1 + f / TAU) % 1.0
        portao = 1.0 - _suave01((pausa - 0.78) / 0.05) * (1.0 - _suave01((pausa - 0.95) / 0.05))
        return float(abertura * portao * min(1.5, self.i))

    def _pintar_boca(self, quadro: np.ndarray, t: float, indice_quadro: int) -> None:
        (cx, cy, w, h), pele, escuro = self._dados["falar"]  # type: ignore[misc]
        o = min(1.0, self._abertura_boca(t, indice_quadro))
        if o < 0.12:
            return
        altura, largura = quadro.shape[:2]
        abertura = max(2.0, o * 0.55 * w)
        folga = max(2, int(round(0.12 * w)))
        px0 = int(max(0, cx - w / 2 - folga - 2))
        px1 = int(min(largura, cx + w / 2 + folga + 3))
        py0 = int(max(0, cy - max(h, abertura) / 2 - folga - 2))
        py1 = int(min(altura, cy + max(h, abertura) + folga + 3))
        trecho = np.ascontiguousarray(quadro[py0:py1, px0:px1])
        c = (cx - px0, cy - py0)
        cv2.ellipse(trecho, (c, (w + 2 * folga, h + 2 * folga), 0.0), tuple(int(v) for v in pele), -1, cv2.LINE_AA)
        centro = (c[0], c[1] + 0.15 * abertura)
        eixos = (w * (0.8 + 0.15 * o), abertura)
        cv2.ellipse(trecho, (centro, eixos, 0.0), (80, 28, 36), -1, cv2.LINE_AA)
        if o > 0.45:
            lingua = (centro[0], centro[1] + 0.22 * abertura)
            cv2.ellipse(trecho, (lingua, (w * 0.5, abertura * 0.42), 0.0), (222, 112, 118), -1, cv2.LINE_AA)
        espessura = max(1, int(round(w * 0.07)))
        cv2.ellipse(trecho, (centro, eixos, 0.0), tuple(int(v) for v in escuro), espessura, cv2.LINE_AA)
        quadro[py0:py1, px0:px1] = trecho

    def _pintar_brilho(self, quadro: np.ndarray, t: float) -> None:
        dados = self._dados.get("brilhar")
        if dados is None:
            return
        (rx0, ry0, rx1, ry1), halo, m, cor = dados  # type: ignore[misc]
        tt = max(0.0, t - self.atraso)
        g = (0.55 + 0.45 * math.sin(TAU * 0.9 * self.v * tt + self.fase)) * self.i
        regiao = quadro[ry0:ry1, rx0:rx1].astype(np.float32)
        alfa_fora = np.clip(halo * (1.0 - m) * 0.65 * g, 0.0, 0.85)[..., None]
        regiao = regiao * (1 - alfa_fora) + cor * alfa_fora
        regiao = regiao + (255.0 - regiao) * (m * 0.22 * g)[..., None]
        quadro[ry0:ry1, rx0:rx1] = np.clip(regiao + 0.5, 0, 255).astype(np.uint8)

    def _pintar_onda(self, quadro: np.ndarray, t: float) -> None:
        gx, gy, peso = self._dados["ondular"]  # type: ignore[misc]
        x0, y0, x1, y1 = self.caixa
        tt = max(0.0, t - self.atraso)
        largura, altura = x1 - x0, y1 - y0
        amplitude = 0.03 * min(largura, altura) * self.i
        comprimento = 0.6 * max(largura, altura)
        fase = TAU * 0.9 * self.v * tt
        dx = amplitude * np.sin(TAU * (gy - y0) / comprimento - fase) * peso
        dy = 0.6 * amplitude * np.sin(TAU * (gx - x0) / comprimento - 1.13 * fase + 1.3) * peso
        mapa_x = (gx + dx - x0).astype(np.float32)
        mapa_y = (gy + dy - y0).astype(np.float32)
        regiao = np.ascontiguousarray(quadro[y0:y1, x0:x1])
        quadro[y0:y1, x0:x1] = cv2.remap(regiao, mapa_x, mapa_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT101)

    def _pintar_codigo(self, quadro: np.ndarray, t: float) -> None:
        (x0, y0, x1, y1), fundo, altura_linha, largura_char, visiveis, linhas, velocidade = self._dados["codigo"]  # type: ignore[misc]
        if x1 - x0 < 6 or y1 - y0 < 6:
            return
        digitados = velocidade * max(0.0, t - self.atraso)
        atual, restante = 0, digitados
        while atual < len(linhas) - 1 and restante >= linhas[atual][2]:
            restante -= linhas[atual][2]
            atual += 1
        primeira = max(0, atual - visiveis + 1)
        tela = np.ascontiguousarray(quadro[y0:y1, x0:x1])
        tela[:] = np.clip(fundo, 0, 255).astype(np.uint8)
        espessura = max(2, int(round(altura_linha * 0.42)))
        cursor_x = 0.0
        cursor_y = 0.0
        for indice in range(primeira, atual + 1):
            _, tokens, _ = linhas[indice]
            y = (indice - primeira) * altura_linha + altura_linha * 0.6
            limite = restante if indice == atual else float("inf")
            for inicio, tamanho, cor in tokens:
                if inicio >= limite:
                    break
                fim = min(inicio + tamanho, limite)
                xa = largura_char * (inicio + 0.6)
                xb = largura_char * (fim + 0.4)
                cv2.line(tela, (int(xa), int(y)), (int(max(xa, xb - espessura / 2)), int(y)), cor, espessura, cv2.LINE_AA)
            if indice == atual:
                cursor_x = largura_char * (min(restante, linhas[indice][2]) + 0.8)
                cursor_y = y
        if (t * 2.0) % 1.0 < 0.6:
            cor_cursor = tuple(int(c) for c in _paleta_codigo(float(fundo @ np.array([0.299, 0.587, 0.114])) < 128)[4])
            meia = max(2, int(altura_linha * 0.35))
            cv2.rectangle(tela, (int(cursor_x), int(cursor_y - meia)), (int(cursor_x + max(2, largura_char * 0.5)), int(cursor_y + meia)),
                          cor_cursor, -1)
        quadro[y0:y1, x0:x1] = tela
