"""Pasta de projeto de um vídeo e seus arquivos.

projetos/<nome-do-video>/
    projeto.json      tema, título, etapa, ritmo e estilo visual (editável)
    titulos.json      títulos sugeridos
    roteiro.md        roteiro (pode editar à mão; é a fonte da verdade)
    cenas.json        plano de cenas completo
    cenas.md          cenas legíveis: narração, prompt e animações
    prompts.txt       um prompt por linha ("cena01: ...") para gerar em lote
    prompts.csv       o mesmo em planilha
    animacoes.md      checklist das animações de cada cena
    narracao.md       texto por cena (para gravar ou gerar a voz)
    legendas.srt      legendas com tempos estimados
    imagens/          coloque aqui cena01.png, cena02.png, ...
    audio/            (opcional) cena01.mp3, ... para sincronizar a boca e a duração
    animacoes/        cena01.json (ajustes), cena01.mp4 (vídeo), cena01_partes.png (conferência)
    video/            vídeo montado
"""

from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path
from typing import Any

from animacao2d import config
from animacao2d.animacao.imagem import EXTENSOES
from animacao2d.estilo import ESTILO_PADRAO, NEGATIVO_PADRAO, SUFIXO_MIDJOURNEY_PADRAO
from animacao2d.util import ler_json, nome_cena, numero_cena_arquivo, salvar_json, slugify

EXTENSOES_AUDIO = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")


class ErroProjeto(RuntimeError):
    pass


class Projeto:
    def __init__(self, pasta: str | Path):
        self.pasta = Path(pasta)
        self.arquivo = self.pasta / "projeto.json"
        if not self.arquivo.is_file():
            raise ErroProjeto(f"{self.pasta} não é um projeto (falta projeto.json).")
        self.dados: dict[str, Any] = ler_json(self.arquivo)

    # ------------------------------------------------------------ criação/abertura

    @classmethod
    def criar(cls, titulo: str, tema: str = "", base: str | Path | None = None, minutos: float = config.MINUTOS_PADRAO,
              ritmo: str = config.RITMO_PADRAO) -> "Projeto":
        raiz = Path(base) if base else config.pasta_projetos()
        slug = slugify(titulo)
        pasta = raiz / slug
        contador = 2
        while pasta.exists():
            pasta = raiz / f"{slug}-{contador}"
            contador += 1
        pasta.mkdir(parents=True)
        for sub in ("imagens", "animacoes", "audio", "video"):
            (pasta / sub).mkdir()
        salvar_json(pasta / "projeto.json", {
            "versao": 1,
            "titulo": titulo,
            "tema": tema or titulo,
            "criado_em": _dt.datetime.now().isoformat(timespec="seconds"),
            "etapa": "titulo_aprovado",
            "minutos": minutos,
            "palavras_por_minuto": config.PALAVRAS_POR_MINUTO,
            "ritmo": ritmo,
            "estilo": ESTILO_PADRAO,
            "negativo": NEGATIVO_PADRAO,
            "sufixo_midjourney": SUFIXO_MIDJOURNEY_PADRAO,
        })
        projeto = cls(pasta)
        projeto.marcar_ultimo()
        return projeto

    @classmethod
    def resolver(cls, argumento: str | None = None) -> "Projeto":
        """Acha o projeto: caminho/nome informado, pasta atual ou o último usado."""
        raiz = config.pasta_projetos()
        candidatos: list[Path] = []
        if argumento:
            candidatos += [Path(argumento), raiz / argumento]
        else:
            candidatos.append(Path.cwd())
            ultimo = raiz / ".ultimo"
            if ultimo.is_file():
                candidatos.append(Path(ultimo.read_text(encoding="utf-8").strip()))
        for candidato in candidatos:
            if (candidato / "projeto.json").is_file():
                projeto = cls(candidato)
                projeto.marcar_ultimo()
                return projeto
        if argumento:
            raise ErroProjeto(f"Projeto '{argumento}' não encontrado (procurei em {raiz}).")
        raise ErroProjeto("Nenhum projeto aberto. Crie um com: animacao2d novo \"tema\" "
                          "(ou indique com -p pasta_do_projeto).")

    def marcar_ultimo(self) -> None:
        raiz = config.pasta_projetos()
        try:
            raiz.mkdir(parents=True, exist_ok=True)
            (raiz / ".ultimo").write_text(str(self.pasta.resolve()), encoding="utf-8")
        except OSError:
            pass

    def salvar(self) -> None:
        salvar_json(self.arquivo, self.dados)

    def definir_etapa(self, etapa: str) -> None:
        self.dados["etapa"] = etapa
        self.salvar()

    # ------------------------------------------------------------ atalhos

    @property
    def titulo(self) -> str:
        return str(self.dados.get("titulo", ""))

    @property
    def nome(self) -> str:
        return self.pasta.name

    def __getattr__(self, nome: str) -> Path:
        arquivos = {
            "roteiro_md": "roteiro.md", "roteiro_json": "roteiro.json", "titulos_json": "titulos.json",
            "cenas_json": "cenas.json", "cenas_md": "cenas.md", "prompts_txt": "prompts.txt",
            "prompts_csv": "prompts.csv", "animacoes_md": "animacoes.md", "narracao_md": "narracao.md",
            "legendas_srt": "legendas.srt", "pasta_imagens": "imagens", "pasta_animacoes": "animacoes",
            "pasta_audio": "audio", "pasta_video": "video",
        }
        if nome in arquivos:
            return self.pasta / arquivos[nome]
        raise AttributeError(nome)

    # ------------------------------------------------------------ cenas

    def cenas(self) -> list[dict]:
        if not self.cenas_json.is_file():
            return []
        return list(ler_json(self.cenas_json).get("cenas", []))

    def cena_planejada(self, numero: int) -> dict | None:
        for cena in self.cenas():
            if int(cena.get("numero", -1)) == numero:
                return cena
        return None

    def _arquivos_por_numero(self, pasta: Path, extensoes: tuple[str, ...]) -> dict[int, Path]:
        encontrados: dict[int, Path] = {}
        if not pasta.is_dir():
            return encontrados
        for arquivo in sorted(pasta.iterdir()):
            if arquivo.suffix.lower() in extensoes and not arquivo.name.startswith("."):
                numero = numero_cena_arquivo(arquivo.name)
                if numero is not None and numero not in encontrados:
                    encontrados[numero] = arquivo
        return encontrados

    def imagens(self) -> dict[int, Path]:
        return self._arquivos_por_numero(self.pasta_imagens, EXTENSOES)

    def audios(self) -> dict[int, Path]:
        return self._arquivos_por_numero(self.pasta_audio, EXTENSOES_AUDIO)

    def imagem_da_cena(self, numero: int) -> Path | None:
        return self.imagens().get(numero)

    def audio_da_cena(self, numero: int) -> Path | None:
        return self.audios().get(numero)

    def spec_da_cena(self, numero: int) -> Path:
        return self.pasta_animacoes / f"{nome_cena(numero)}.json"

    def video_da_cena(self, numero: int) -> Path:
        return self.pasta_animacoes / f"{nome_cena(numero)}.mp4"

    def previa_da_cena(self, numero: int) -> Path:
        return self.pasta_animacoes / f"{nome_cena(numero)}_partes.png"

    def caminho_relativo(self, destino: Path, origem: Path) -> str:
        """Caminho de `destino` relativo à pasta de `origem` (para gravar no JSON)."""
        try:
            return Path(os.path.relpath(destino, origem.parent)).as_posix()
        except ValueError:  # discos diferentes no Windows
            return str(destino)
