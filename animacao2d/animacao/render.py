"""Renderizador de cena: aplica efeitos, compõe as partes móveis e a câmera."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, Iterator

import cv2
import numpy as np

from animacao2d import config
from animacao2d.animacao.camera import matriz_camera
from animacao2d.animacao.efeitos import ParteAnimada, Pose, _suave01
from animacao2d.animacao.imagem import carregar_rgb
from animacao2d.animacao.mascara import bbox_mascara, calcular_mascara, remover_partes
from animacao2d.animacao.spec import SpecCena
from animacao2d.animacao.video import EscritorVideo, envelope_audio
from animacao2d.util import sem_acentos

CORES_PARTES = [(255, 99, 71), (65, 145, 255), (60, 200, 120), (255, 190, 40), (190, 100, 255),
                (0, 200, 200), (255, 120, 190), (140, 140, 140)]


class RenderizadorCena:
    def __init__(self, spec: SpecCena, pasta_base: str | Path = ".", largura: int = config.LARGURA_VIDEO,
                 altura: int = config.ALTURA_VIDEO, fps: float = config.FPS, duracao: float | None = None,
                 imagem: np.ndarray | None = None, audio_boca: str | Path | None = None):
        self.spec = spec
        self.largura_saida, self.altura_saida = int(largura), int(altura)
        self.fps = float(fps)
        self.duracao = float(duracao if duracao else spec.duracao)
        self.total_quadros = max(1, int(round(self.duracao * self.fps)))
        original = imagem if imagem is not None else carregar_rgb(spec.caminho_imagem(Path(pasta_base)))
        altura0, largura0 = original.shape[:2]
        spec.ajustar_tamanho(largura0, altura0)

        # resolução de trabalho: cobre a saída em 1:1 (ou 1,25x se a imagem for grande)
        cobertura = max(self.largura_saida / largura0, self.altura_saida / altura0)
        self.escala = cobertura if cobertura >= 1.0 else min(1.0, cobertura * 1.25)
        if abs(self.escala - 1.0) > 1e-3:
            interp = cv2.INTER_CUBIC if self.escala > 1 else cv2.INTER_AREA
            nova = (max(2, int(round(largura0 * self.escala))), max(2, int(round(altura0 * self.escala))))
            self.img = cv2.resize(original, nova, interpolation=interp)
        else:
            self.img = np.ascontiguousarray(original)
        self.altura, self.largura = self.img.shape[:2]
        self.foco = None
        if spec.camera.foco is not None:
            self.foco = (spec.camera.foco[0] * self.escala, spec.camera.foco[1] * self.escala)

        self.partes = [ParteAnimada(p, self.img, self.escala, self.duracao, semente=i + 1)
                       for i, p in enumerate(spec.partes)]
        self.modos_mascara: dict[str, str] = {}
        for pa in self.partes:
            pa.fps = self.fps
            if pa.precisa_mascara:
                membro = pa.pivo if any(a in ("acenar", "balancar") for a in pa.movimentos) else None
                pa.mascara, modo = calcular_mascara(self.img, pa.caixa, pa.modo_mascara, pa.redonda, membro)
                self.modos_mascara[pa.nome] = modo
                pa.preparar_brilho(self.img)
        if audio_boca:
            envelope = envelope_audio(audio_boca, self.fps, self.total_quadros)
            for pa in self.partes:
                if "falar" in pa.pinturas:
                    pa.envelope_boca = envelope
        self._preparar_moveis()

    # ------------------------------------------------------------ preparo

    def _preparar_moveis(self) -> None:
        moveis = [pa for pa in self.partes if pa.movimentos and pa.mascara is not None]
        # as maiores ficam atrás; cada parte "fura" a máscara das que estão atrás dela
        moveis.sort(key=lambda pa: -float(pa.mascara.sum()))  # type: ignore[union-attr]
        self.moveis: list[tuple[ParteAnimada, tuple[int, int, int, int], np.ndarray, dict]] = []
        uniao = np.zeros((self.altura, self.largura), np.float32)
        for indice, pa in enumerate(moveis):
            alfa = pa.mascara.copy()  # type: ignore[union-attr]
            for frente in moveis[indice + 1:]:
                alfa *= 1.0 - frente.mascara  # type: ignore[operator]
            np.maximum(uniao, pa.mascara, out=uniao)  # type: ignore[arg-type]
            caixa = bbox_mascara(alfa)
            if caixa is None:
                continue
            x0, y0, x1, y1 = caixa
            self.moveis.append((pa, caixa, np.ascontiguousarray(alfa[y0:y1, x0:x1]), self._geometria(pa, caixa)))
        self.fundo = None
        self.buracos: list[tuple[tuple[int, int, int, int], np.ndarray]] = []
        if self.moveis:
            # o fundo só é trocado dentro do buraco (já com folga em volta das peças),
            # assim o contorno original não deixa "fantasma" quando a peça se move
            self.fundo, buraco = remover_partes(self.img, uniao)
            suave = cv2.GaussianBlur(buraco.astype(np.float32) / 255.0, (0, 0), 1.0)
            n, _, stats, _ = cv2.connectedComponentsWithStats((suave > 0.005).astype(np.uint8), connectivity=8)
            for i in range(1, n):
                x, y, w, h, _ = stats[i]
                self.buracos.append(((x, y, x + w, y + h), np.ascontiguousarray(suave[y:y + h, x:x + w][..., None])))
        self._sincronizar_piscadas()

    def _sincronizar_piscadas(self) -> None:
        """Olhos próximos (do mesmo personagem) piscam juntos."""
        olhos = [pa for pa in self.partes if "piscar" in pa.pinturas]
        grupos: list[list[ParteAnimada]] = []
        for pa in olhos:
            x0, y0, x1, y1 = pa.caixa
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            alcance = max(4.0 * max(x1 - x0, y1 - y0), 0.08 * self.altura)
            for grupo in grupos:
                g = grupo[0].caixa
                if math.hypot(cx - (g[0] + g[2]) / 2, cy - (g[1] + g[3]) / 2) <= alcance:
                    grupo.append(pa)
                    break
            else:
                grupos.append([pa])
        for grupo in grupos:
            _, _, piscadas = grupo[0]._dados["piscar"]  # type: ignore[misc]
            for pa in grupo[1:]:
                olhos_pa, pele, _ = pa._dados["piscar"]  # type: ignore[misc]
                pa._dados["piscar"] = (olhos_pa, pele, piscadas)

    @staticmethod
    def _geometria(pa: ParteAnimada, caixa: tuple[int, int, int, int]) -> dict:
        x0, y0, x1, y1 = caixa
        px, py = pa.pivo
        cantos = [(x0, y0), (x1, y0), (x0, y1), (x1, y1)]
        comprimento = max(math.hypot(cx - px, cy - py) for cx, cy in cantos)
        return {"raio_interno": 0.12 * comprimento, "raio_externo": 0.5 * comprimento}

    # ------------------------------------------------------------ quadros

    def quadro_fonte(self, t: float, indice: int = 0) -> np.ndarray:
        """Quadro na resolução de trabalho, antes da câmera."""
        quadro = self.img.copy()
        for pa in self.partes:
            if pa.pinturas:
                pa.pintar(quadro, t, indice)
        if not self.moveis:
            return quadro
        tela = quadro.copy()
        for (x0, y0, x1, y1), peso in self.buracos:
            regiao = tela[y0:y1, x0:x1].astype(np.float32)
            fundo = self.fundo[y0:y1, x0:x1].astype(np.float32)  # type: ignore[index]
            tela[y0:y1, x0:x1] = (regiao + (fundo - regiao) * peso + 0.5).astype(np.uint8)
        for pa, caixa, alfa, geometria in self.moveis:
            self._compor(tela, quadro, pa, caixa, alfa, geometria, pa.pose(t))
        return tela

    def _compor(self, tela: np.ndarray, quadro: np.ndarray, pa: ParteAnimada, caixa, alfa: np.ndarray,
                geometria: dict, pose: Pose) -> None:
        sx0, sy0, sx1, sy1 = caixa
        if pose.alfa <= 0.001:
            return
        rgb = quadro[sy0:sy1, sx0:sx1].astype(np.float32) * alfa[..., None]
        if pose.identidade():
            dx0, dy0, dx1, dy1 = sx0, sy0, sx1, sy1
            camada_rgb, camada_a = rgb, alfa
        else:
            px, py = pa.pivo
            ax, ay = pose.ancora or pa.pivo
            teta = math.radians(pose.angulo)

            def frente(x: float, y: float, fracao: float) -> tuple[float, float]:
                c, s = math.cos(teta * fracao), math.sin(teta * fracao)
                qx, qy = x - px, y - py
                x1_, y1_ = px + c * qx - s * qy, py + s * qx + c * qy
                return ax + (x1_ - ax) * pose.sx + pose.dx, ay + (y1_ - ay) * pose.sy + pose.dy

            pontos = [frente(x, y, f) for x in (sx0, sx1) for y in (sy0, sy1) for f in (0.0, 0.5, 1.0)]
            xs, ys = [p[0] for p in pontos], [p[1] for p in pontos]
            dx0 = max(0, int(math.floor(min(xs))) - 2)
            dy0 = max(0, int(math.floor(min(ys))) - 2)
            dx1 = min(self.largura, int(math.ceil(max(xs))) + 2)
            dy1 = min(self.altura, int(math.ceil(max(ys))) + 2)
            if dx1 <= dx0 or dy1 <= dy0:
                return
            gx, gy = np.meshgrid(np.arange(dx0, dx1, dtype=np.float32), np.arange(dy0, dy1, dtype=np.float32))
            # inversa: desfaz translação, escala e rotação (nessa ordem)
            ux = ax + (gx - pose.dx - ax) / pose.sx
            uy = ay + (gy - pose.dy - ay) / pose.sy
            qx, qy = ux - px, uy - py
            if pose.macio:
                raio = np.sqrt(qx * qx + qy * qy)
                peso = _suave01((raio - geometria["raio_interno"]) /
                                max(1e-3, geometria["raio_externo"] - geometria["raio_interno"]))
                angulo = -teta * peso
                c, s = np.cos(angulo), np.sin(angulo)
            else:
                c, s = math.cos(-teta), math.sin(-teta)
            mapa_x = (px + c * qx - s * qy - sx0).astype(np.float32)
            mapa_y = (py + s * qx + c * qy - sy0).astype(np.float32)
            camada_rgb = cv2.remap(rgb, mapa_x, mapa_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
            camada_a = cv2.remap(alfa, mapa_x, mapa_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        a = (camada_a * pose.alfa)[..., None]
        regiao = tela[dy0:dy1, dx0:dx1].astype(np.float32)
        regiao = regiao * (1.0 - a) + camada_rgb * pose.alfa
        tela[dy0:dy1, dx0:dx1] = np.clip(regiao + 0.5, 0, 255).astype(np.uint8)

    def quadro(self, indice: int) -> np.ndarray:
        t = indice / self.fps
        fonte = self.quadro_fonte(t, indice)
        matriz = matriz_camera(self.spec.camera, t, self.duracao, self.largura, self.altura,
                               self.largura_saida, self.altura_saida, self.foco)
        return cv2.warpAffine(fonte, matriz, (self.largura_saida, self.altura_saida), flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_REFLECT101)

    def quadros(self) -> Iterator[np.ndarray]:
        for indice in range(self.total_quadros):
            yield self.quadro(indice)

    def renderizar(self, caminho: str | Path, progresso: Callable[[int, int], None] | None = None,
                   audio: str | Path | None = None, preset: str = "medium", crf: int = 18) -> Path:
        with EscritorVideo(caminho, self.largura_saida, self.altura_saida, self.fps, crf=crf, preset=preset,
                           audio=audio) as escritor:
            for indice, quadro in enumerate(self.quadros()):
                escritor.escrever(quadro)
                if progresso:
                    progresso(indice + 1, self.total_quadros)
        return Path(caminho)

    # ------------------------------------------------------------ prévia

    def previa(self, com_rotulos: bool = True) -> np.ndarray:
        """Imagem com as máscaras coloridas, caixas, pivôs e nomes (para conferência)."""
        vis = self.img.astype(np.float32)
        for i, pa in enumerate(self.partes):
            cor = np.array(CORES_PARTES[i % len(CORES_PARTES)], np.float32)
            if pa.mascara is not None:
                vis = vis * (1 - 0.45 * pa.mascara[..., None]) + cor * 0.45 * pa.mascara[..., None]
        vis = np.clip(vis, 0, 255).astype(np.uint8)
        if not com_rotulos:
            return vis
        espessura = max(2, int(round(min(self.largura, self.altura) / 400)))
        fonte = max(0.5, min(self.largura, self.altura) / 1100)
        for i, pa in enumerate(self.partes):
            cor = CORES_PARTES[i % len(CORES_PARTES)]
            x0, y0, x1, y1 = pa.caixa
            cv2.rectangle(vis, (x0, y0), (x1, y1), cor, espessura, cv2.LINE_AA)
            if pa.movimentos:
                px, py = int(pa.pivo[0]), int(pa.pivo[1])
                r = 4 * espessura
                cv2.circle(vis, (px, py), r, (255, 255, 255), -1, cv2.LINE_AA)
                cv2.circle(vis, (px, py), r, cor, espessura, cv2.LINE_AA)
            rotulo = sem_acentos(f"{pa.nome}: {'+'.join(pa.parte.animacoes)}")
            (lw, lh), base = cv2.getTextSize(rotulo, cv2.FONT_HERSHEY_SIMPLEX, fonte, max(1, espessura - 1))
            ty = y0 - 6 if y0 - lh - 10 > 0 else y1 + lh + 8
            cv2.rectangle(vis, (x0, ty - lh - 4), (x0 + lw + 6, ty + base), cor, -1)
            cv2.putText(vis, rotulo, (x0 + 3, ty - 2), cv2.FONT_HERSHEY_SIMPLEX, fonte, (255, 255, 255),
                        max(1, espessura - 1), cv2.LINE_AA)
        return vis


def renderizar_cena(spec: SpecCena, pasta_base: str | Path, saida: str | Path, **opcoes) -> Path:
    return RenderizadorCena(spec, pasta_base, **opcoes).renderizar(saida)
