"""Montagem do vídeo completo: todas as cenas em ordem, com áudio opcional.

Duração de cada cena (nesta ordem de prioridade):
1. áudio próprio da cena (audio/cena01.mp3...), se existir;
2. duração do arquivo de ajustes (animacoes/cena01.json);
3. duração planejada em cenas.json.
Com --audio narracao.mp3 (um áudio único), as durações são esticadas/encolhidas
proporcionalmente para o vídeo terminar junto com a narração.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import cv2
import numpy as np

from animacao2d import config
from animacao2d.animacao.imagem import tamanho_imagem
from animacao2d.animacao.render import RenderizadorCena
from animacao2d.animacao.spec import Camera, SpecCena
from animacao2d.animacao.video import EscritorVideo, duracao_midia, ffmpeg_exe
from animacao2d.projeto import Projeto
from animacao2d.util import formatar_tempo, nome_cena

TAXA_AUDIO = 44100


def _ler_pcm(caminho: Path) -> np.ndarray:
    processo = subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-i", str(caminho), "-ac", "2",
                               "-ar", str(TAXA_AUDIO), "-f", "s16le", "-"], capture_output=True)
    if processo.returncode != 0:
        raise ValueError(f"Não consegui ler o áudio {caminho}")
    return np.frombuffer(processo.stdout, dtype=np.int16).reshape(-1, 2)


def _faixa_por_cena(trechos: list[tuple[Path | None, float]], destino: Path) -> Path:
    """Junta os áudios das cenas (silêncio onde não há) num único WAV."""
    blocos = []
    for audio, duracao in trechos:
        amostras = int(round(duracao * TAXA_AUDIO))
        bloco = np.zeros((amostras, 2), np.int16)
        if audio is not None:
            pcm = _ler_pcm(audio)[:amostras]
            bloco[:len(pcm)] = pcm
        blocos.append(bloco)
    with wave.open(str(destino), "wb") as arquivo:
        arquivo.setnchannels(2)
        arquivo.setsampwidth(2)
        arquivo.setframerate(TAXA_AUDIO)
        arquivo.writeframes(np.concatenate(blocos).tobytes() if blocos else b"")
    return destino


def _quadro_faltando(largura: int, altura: int, texto: str) -> np.ndarray:
    quadro = np.full((altura, largura, 3), 38, np.uint8)
    escala = largura / 1300
    (lt, at), _ = cv2.getTextSize(texto, cv2.FONT_HERSHEY_SIMPLEX, escala, 2)
    cv2.putText(quadro, texto, ((largura - lt) // 2, (altura + at) // 2), cv2.FONT_HERSHEY_SIMPLEX, escala,
                (200, 200, 200), 2, cv2.LINE_AA)
    return quadro


def montar_video(projeto: Projeto, saida: str | Path | None = None, audio: str | Path | None = None,
                 previa: bool = False) -> Path:
    planejadas = {int(c["numero"]): c for c in projeto.cenas()}
    imagens = projeto.imagens()
    audios = projeto.audios()
    numeros = sorted(set(planejadas) | set(imagens))
    if not numeros:
        raise FileNotFoundError("Não há cenas planejadas nem imagens em imagens/ para montar.")

    duracoes: dict[int, float] = {}
    for n in numeros:
        if n in audios:
            duracoes[n] = duracao_midia(audios[n]) + 0.15
        elif projeto.spec_da_cena(n).is_file():
            duracoes[n] = SpecCena.carregar(projeto.spec_da_cena(n)).duracao
        else:
            duracoes[n] = float(planejadas.get(n, {}).get("duracao") or 5.0)
    if audio and not audios:
        total_audio = duracao_midia(audio)
        fator = total_audio / max(1e-6, sum(duracoes.values()))
        duracoes = {n: d * fator for n, d in duracoes.items()}
        print(f"Ajustando as cenas ao áudio ({formatar_tempo(total_audio)}): fator {fator:.3f}", file=sys.stderr)

    largura, altura = (960, 540) if previa else (config.LARGURA_VIDEO, config.ALTURA_VIDEO)
    fps = config.FPS
    destino = Path(saida) if saida else projeto.pasta_video / ("previa.mp4" if previa else "video_completo.mp4")
    faixa: Path | None = Path(audio) if audio else None
    temporario = None
    if audios:
        temporario = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        temporario.close()
        faixa = _faixa_por_cena([(audios.get(n), duracoes[n]) for n in numeros], Path(temporario.name))

    faltando = [nome_cena(n) for n in numeros if n not in imagens]
    total_quadros = int(round(sum(duracoes.values()) * fps))
    feitos, relogio = 0, 0.0
    interativo = sys.stderr.isatty()
    try:
        with EscritorVideo(destino, largura, altura, fps, preset="veryfast" if previa else "medium",
                           audio=faixa) as escritor:
            for n in numeros:
                inicio_q = int(round(relogio * fps))
                relogio += duracoes[n]
                quadros = int(round(relogio * fps)) - inicio_q
                if quadros <= 0:
                    continue
                if n in imagens:
                    spec_arquivo = projeto.spec_da_cena(n)
                    if spec_arquivo.is_file():
                        spec = SpecCena.carregar(spec_arquivo)
                        base = spec_arquivo.parent
                    else:
                        w, h = tamanho_imagem(imagens[n])
                        camera = planejadas.get(n, {}).get("camera") or "zoom_in"
                        spec = SpecCena(imagem=str(imagens[n].resolve()), largura=w, altura=h,
                                        duracao=duracoes[n], camera=Camera(movimento=camera))
                        base = projeto.pasta
                    spec.imagem = str(imagens[n].resolve())  # sempre a imagem atual da pasta imagens/
                    falar = any("falar" in p.animacoes for p in spec.partes)
                    renderizador = RenderizadorCena(spec, base, largura, altura, fps, duracao=duracoes[n],
                                                    audio_boca=audios.get(n) if falar else None)
                    for i in range(quadros):
                        escritor.escrever(renderizador.quadro(i))
                        feitos += 1
                        if interativo and feitos % 30 == 0:
                            sys.stderr.write(f"\rMontando: {100 * feitos // max(1, total_quadros):3d}% "
                                             f"({nome_cena(n)})   ")
                            sys.stderr.flush()
                else:
                    quadro = _quadro_faltando(largura, altura, f"{nome_cena(n)} - imagem faltando")
                    for _ in range(quadros):
                        escritor.escrever(quadro)
                        feitos += 1
    finally:
        if temporario is not None:
            Path(temporario.name).unlink(missing_ok=True)
    sys.stderr.write(f"\rMontando: 100%{' ' * 30}\n" if interativo else "Montagem concluída.\n")
    if faltando:
        print(f"Aviso: {len(faltando)} cena(s) sem imagem viraram tela cinza: {', '.join(faltando[:15])}"
              + (" ..." if len(faltando) > 15 else ""), file=sys.stderr)
    return destino
