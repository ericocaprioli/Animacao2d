"""Gravação de MP4 (H.264) e leitura de áudio via o ffmpeg que vem no imageio-ffmpeg."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import numpy as np


def ffmpeg_exe() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


class EscritorVideo:
    """Recebe quadros RGB uint8 e grava um MP4 compatível com qualquer editor."""

    def __init__(self, caminho: str | Path, largura: int, altura: int, fps: float = 30,
                 crf: int = 18, preset: str = "medium", audio: str | Path | None = None):
        import imageio_ffmpeg

        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        parametros = ["-crf", str(crf), "-preset", preset, "-movflags", "+faststart"]
        if audio:
            parametros += ["-shortest"]
        self._gerador = imageio_ffmpeg.write_frames(
            str(self.caminho), (largura, altura), fps=fps, codec="libx264", quality=None,
            pix_fmt_in="rgb24", pix_fmt_out="yuv420p", macro_block_size=2,
            ffmpeg_log_level="error", output_params=parametros,
            audio_path=str(audio) if audio else None, audio_codec="aac" if audio else None,
        )
        self._gerador.send(None)
        self.quadros = 0

    def escrever(self, quadro: np.ndarray) -> None:
        self._gerador.send(np.ascontiguousarray(quadro, dtype=np.uint8))
        self.quadros += 1

    def fechar(self) -> None:
        self._gerador.close()

    def __enter__(self) -> "EscritorVideo":
        return self

    def __exit__(self, *exc) -> None:
        self.fechar()


def duracao_midia(caminho: str | Path) -> float:
    """Duração (s) de um arquivo de áudio/vídeo lendo a saída do ffmpeg."""
    processo = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(caminho)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
    achado = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", processo.stderr)
    if not achado:
        raise ValueError(f"Não consegui ler a duração de {caminho}")
    h, m, s = achado.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def envelope_audio(caminho: str | Path, fps: float, quadros: int) -> np.ndarray:
    """Volume (0..1) por quadro, usado para sincronizar a boca com a fala."""
    taxa = 16000
    processo = subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-i", str(caminho), "-ac", "1", "-ar", str(taxa),
         "-f", "s16le", "-"],
        capture_output=True,
    )
    if processo.returncode != 0:
        raise ValueError(f"Não consegui ler o áudio {caminho}: {processo.stderr.decode(errors='replace')[:300]}")
    amostras = np.frombuffer(processo.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    por_quadro = taxa / fps
    volumes = np.zeros(quadros, np.float32)
    for i in range(quadros):
        trecho = amostras[int(i * por_quadro):int((i + 1) * por_quadro)]
        if len(trecho):
            volumes[i] = float(np.sqrt(np.mean(trecho * trecho)))
    referencia = float(np.percentile(volumes[volumes > 0], 90)) if (volumes > 0).any() else 0.0
    if referencia <= 1e-6:
        return np.zeros(quadros, np.float32)
    abertura = np.clip((volumes / referencia - 0.12) / 0.8, 0.0, 1.0)
    # suaviza um pouco para não "tremer" a boca
    suave = np.convolve(abertura, np.array([0.25, 0.5, 0.25], np.float32), mode="same")
    return suave.astype(np.float32)
