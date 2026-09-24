"""Utilitários gerais: console, JSON, nomes de cena, tempo e progresso."""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any


def configurar_console() -> None:
    """Evita que acentos quebrem o programa em consoles antigos do Windows."""
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def sem_acentos(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in normalizado if not unicodedata.combining(c))


def slugify(texto: str, limite: int = 60) -> str:
    base = sem_acentos(texto).lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return (base[:limite].rstrip("-")) or "projeto"


def ler_json(caminho: str | os.PathLike) -> Any:
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def salvar_json(caminho: str | os.PathLike, dados: Any) -> None:
    """Grava JSON legível (UTF-8, acentos preservados) de forma atômica."""
    destino = Path(caminho)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_name(destino.name + ".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporario, destino)


def salvar_texto(caminho: str | os.PathLike, texto: str, codificacao: str = "utf-8") -> None:
    destino = Path(caminho)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto, encoding=codificacao)


def extrair_json(texto: str) -> Any:
    """Extrai o primeiro objeto/array JSON de um texto (aceita blocos ```json)."""
    texto = texto.strip()
    bloco = re.search(r"```(?:json)?\s*(.*?)```", texto, flags=re.S)
    candidatos = [bloco.group(1)] if bloco else []
    candidatos.append(texto)
    for candidato in candidatos:
        candidato = candidato.strip()
        try:
            return json.loads(candidato)
        except json.JSONDecodeError:
            pass
        inicio = min((i for i in (candidato.find("{"), candidato.find("[")) if i >= 0), default=-1)
        if inicio >= 0:
            try:
                valor, _ = json.JSONDecoder().raw_decode(candidato[inicio:])
                return valor
            except json.JSONDecodeError:
                pass
    raise ValueError("Não encontrei um JSON válido na resposta.")


# ---------------------------------------------------------------- cenas

_RE_CENA = re.compile(r"(?i)^\s*(?:cena|scene|c)?[\s_\-]*0*(\d{1,4})\s*$")
_RE_CENA_ARQUIVO = re.compile(r"(?i)(?:cena|scene)[\s_\-]*0*(\d{1,4})")


def numero_cena(identificador: str | int) -> int:
    """'cena01', 'Cena 1', '01', 1 -> 1."""
    if isinstance(identificador, int):
        return identificador
    texto = Path(str(identificador)).stem
    achado = _RE_CENA.match(texto) or _RE_CENA_ARQUIVO.search(texto)
    if not achado:
        raise ValueError(f"Não entendi o número da cena em '{identificador}'. Use algo como cena01.")
    return int(achado.group(1))


def numero_cena_arquivo(nome: str) -> int | None:
    achado = _RE_CENA_ARQUIVO.search(Path(nome).stem)
    return int(achado.group(1)) if achado else None


def nome_cena(numero: int) -> str:
    return f"cena{numero:02d}"


# ---------------------------------------------------------------- texto/tempo

def contar_palavras(texto: str) -> int:
    return len(re.findall(r"[\wÀ-ÿ$%'’-]+", texto))


def formatar_tempo(segundos: float) -> str:
    segundos = max(0.0, float(segundos))
    minutos, resto = divmod(int(round(segundos)), 60)
    return f"{minutos}:{resto:02d}"


def formatar_srt(segundos: float) -> str:
    ms = int(round(max(0.0, segundos) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ---------------------------------------------------------------- interação

class Progresso:
    """Indicador simples de atividade no terminal (ASCII, seguro no Windows)."""

    def __init__(self, mensagem: str, ativo: bool | None = None):
        self.mensagem = mensagem
        self.ativo = sys.stderr.isatty() if ativo is None else ativo
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self._inicio = 0.0
        self.detalhe = ""

    def __enter__(self) -> "Progresso":
        self._inicio = time.monotonic()
        if self.ativo:
            self._thread = threading.Thread(target=self._girar, daemon=True)
            self._thread.start()
        else:
            print(f"{self.mensagem}...", file=sys.stderr, flush=True)
        return self

    def _girar(self) -> None:
        simbolos = "|/-\\"
        i = 0
        while not self._parar.wait(0.2):
            decorrido = time.monotonic() - self._inicio
            extra = f" {self.detalhe}" if self.detalhe else ""
            sys.stderr.write(f"\r{simbolos[i % 4]} {self.mensagem}... {decorrido:4.0f}s{extra}   ")
            sys.stderr.flush()
            i += 1

    def __exit__(self, tipo, valor, rastro) -> None:
        self._parar.set()
        if self._thread:
            self._thread.join()
            sys.stderr.write("\r" + " " * 100 + "\r")
            sys.stderr.flush()
        decorrido = time.monotonic() - self._inicio
        status = "ok" if tipo is None else "falhou"
        print(f"{self.mensagem}: {status} ({decorrido:.0f}s)", file=sys.stderr, flush=True)


def perguntar(pergunta: str, padrao: str = "") -> str:
    try:
        resposta = input(pergunta).strip()
    except EOFError:
        resposta = ""
    return resposta or padrao
