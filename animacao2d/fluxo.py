"""Etapas do fluxo (usadas pela linha de comando e pelo editor visual)."""

from __future__ import annotations

import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from animacao2d import config
from animacao2d.animacao.detectar import detectar_partes, nova_spec, partes_provisorias
from animacao2d.animacao.imagem import aviso_proporcao, salvar_rgb, tamanho_imagem
from animacao2d.animacao.render import RenderizadorCena
from animacao2d.animacao.spec import Camera, SpecCena
from animacao2d.animacao.video import duracao_midia
from animacao2d.cenas import (csv_prompts, gerar_cenas, markdown_animacoes, markdown_cenas, markdown_narracao,
                              montar_prompt, pedido_de_animacao, plano_completo, srt_legendas, texto_prompts)
from animacao2d.llm import ClienteIA
from animacao2d.projeto import Projeto
from animacao2d.roteiro import Roteiro, escrever_roteiro
from animacao2d.util import ler_json, nome_cena, salvar_json, salvar_texto

# ---------------------------------------------------------------- roteiro


def salvar_roteiro(projeto: Projeto, roteiro: Roteiro) -> None:
    salvar_texto(projeto.roteiro_md, roteiro.para_markdown())
    salvar_json(projeto.roteiro_json, roteiro.para_dict())


def carregar_roteiro(projeto: Projeto) -> Roteiro:
    if not projeto.roteiro_md.is_file():
        raise FileNotFoundError(f"Ainda não há roteiro em {projeto.roteiro_md}. Rode: animacao2d roteiro")
    roteiro = Roteiro.de_markdown(projeto.roteiro_md.read_text(encoding="utf-8"))
    if not roteiro.secoes:
        raise ValueError(f"{projeto.roteiro_md} não tem seções no formato '## [tipo] Título'.")
    roteiro.titulo = roteiro.titulo or projeto.titulo
    return roteiro


def gerar_roteiro(projeto: Projeto, ia: ClienteIA, pedido: str = "", partir_do_atual: bool = False) -> Roteiro:
    anterior = carregar_roteiro(projeto) if partir_do_atual and projeto.roteiro_md.is_file() else None
    roteiro = escrever_roteiro(ia, projeto.titulo, projeto.dados.get("tema", projeto.titulo),
                               float(projeto.dados.get("minutos", config.MINUTOS_PADRAO)),
                               float(projeto.dados.get("palavras_por_minuto", config.PALAVRAS_POR_MINUTO)),
                               pedido, anterior,
                               # no modo manual não refaz sozinho (cada rodada é um copiar/colar seu)
                               ajustar_tamanho=ia.nome != "manual")
    salvar_roteiro(projeto, roteiro)
    projeto.definir_etapa("roteiro")
    return roteiro


# ---------------------------------------------------------------- cenas


def gerar_plano_de_cenas(projeto: Projeto, ia: ClienteIA, ritmo: str | None = None, paralelo: int = 1) -> dict:
    roteiro = carregar_roteiro(projeto)
    ritmo = ritmo or projeto.dados.get("ritmo", config.RITMO_PADRAO)
    if ritmo not in config.RITMOS:
        raise ValueError(f"Ritmo '{ritmo}' inválido. Use: {', '.join(config.RITMOS)}")
    ppm = float(projeto.dados.get("palavras_por_minuto", config.PALAVRAS_POR_MINUTO))
    cenas = gerar_cenas(ia, roteiro, ritmo, ppm, projeto.dados.get("estilo", ""), paralelo=paralelo)
    plano = plano_completo(roteiro, cenas, ritmo, ppm, projeto.dados.get("estilo", ""),
                           projeto.dados.get("negativo", ""))
    salvar_json(projeto.cenas_json, plano)
    projeto.dados["ritmo"] = ritmo
    projeto.definir_etapa("cenas")
    exportar_arquivos(projeto)
    return plano


def exportar_arquivos(projeto: Projeto) -> list[Path]:
    """(Re)gera cenas.md, prompts.txt/csv, animacoes.md, narracao.md e legendas.srt a partir de cenas.json."""
    plano = ler_json(projeto.cenas_json)
    estilo = projeto.dados.get("estilo", plano.get("estilo", ""))
    plano["estilo"] = estilo
    plano["negativo"] = projeto.dados.get("negativo", plano.get("negativo", ""))
    personagens = {p["tag"]: p["descricao_visual"] for p in plano.get("personagens", [])}
    for cena in plano["cenas"]:
        cena["prompt"] = montar_prompt(cena.get("prompt_base", ""), personagens, estilo)
    salvar_json(projeto.cenas_json, plano)
    sufixo = projeto.dados.get("sufixo_midjourney", "")
    arquivos = {
        projeto.cenas_md: markdown_cenas(plano, sufixo),
        projeto.prompts_txt: texto_prompts(plano, sufixo),
        projeto.prompts_csv: csv_prompts(plano),
        projeto.animacoes_md: markdown_animacoes(plano),
        projeto.narracao_md: markdown_narracao(plano),
        projeto.legendas_srt: srt_legendas(plano),
    }
    for caminho, conteudo in arquivos.items():
        # CSV com BOM: o Excel no Windows só mostra os acentos certos assim
        salvar_texto(caminho, conteudo, "utf-8-sig" if caminho.suffix == ".csv" else "utf-8")
    return list(arquivos)


# ---------------------------------------------------------------- animação


@dataclass
class AlvoCena:
    """Onde ficam imagem, ajustes (json), vídeo e prévia de uma cena."""

    imagem: Path
    spec: Path
    video: Path
    previa: Path
    numero: int | None = None
    planejada: dict | None = None
    audio: Path | None = None

    @classmethod
    def avulso(cls, imagem: str | Path) -> "AlvoCena":
        imagem = Path(imagem)
        return cls(imagem, imagem.with_suffix(".json"), imagem.with_suffix(".mp4"),
                   imagem.with_name(imagem.stem + "_partes.png"))

    @classmethod
    def do_projeto(cls, projeto: Projeto, numero: int) -> "AlvoCena":
        imagem = projeto.imagem_da_cena(numero)
        if imagem is None:
            raise FileNotFoundError(f"Não achei a imagem da {nome_cena(numero)} em {projeto.pasta_imagens} "
                                    f"(nomeie como {nome_cena(numero)}.png ou .jpg).")
        return cls(imagem, projeto.spec_da_cena(numero), projeto.video_da_cena(numero), projeto.previa_da_cena(numero),
                   numero, projeto.cena_planejada(numero), projeto.audio_da_cena(numero))


def preparar_spec(alvo: AlvoCena, ia: ClienteIA | None, pedido: str = "", duracao: float | None = None,
                  camera: str | None = None, redetectar: bool = False, sem_ia: bool = False,
                  avisar=print) -> SpecCena:
    """Carrega os ajustes da cena ou cria novos (localizando as partes com a IA)."""
    duracao_audio = None
    if alvo.audio is not None:
        try:
            duracao_audio = duracao_midia(alvo.audio) + 0.15
        except ValueError as erro:
            avisar(f"Aviso: {erro}")
    planejada = alvo.planejada or {}
    aviso = aviso_proporcao(*tamanho_imagem(alvo.imagem), nome=alvo.imagem.name)
    if aviso:
        avisar(f"Aviso: {aviso}")

    if alvo.spec.is_file() and not pedido and not redetectar:
        spec = SpecCena.carregar(alvo.spec)
        largura, altura = tamanho_imagem(alvo.imagem)
        spec.ajustar_tamanho(largura, altura)
        spec.imagem = caminho_relativo(alvo.imagem, alvo.spec)
        spec.duracao = duracao or duracao_audio or spec.duracao
        if camera:
            spec.camera = Camera(movimento=camera, intensidade=spec.camera.intensidade, foco=spec.camera.foco)
        spec.salvar(alvo.spec)
        return spec

    pedido = pedido or pedido_de_animacao(planejada)
    duracao_final = duracao or duracao_audio or float(planejada.get("duracao") or 0) or 5.0
    camera_final = camera or planejada.get("camera") or "zoom_in"
    partes = []
    if pedido:
        if sem_ia or ia is None:
            partes = partes_provisorias(pedido, *tamanho_imagem(alvo.imagem))
            avisar("Sem IA: criei caixas provisórias no meio da imagem. Ajuste-as no editor: animacao2d editor")
        else:
            contexto = planejada.get("descricao", "")
            partes, nao_achados, camera_sugerida = detectar_partes(ia, alvo.imagem, pedido, contexto)
            if not camera and not planejada.get("camera"):
                camera_final = camera_sugerida
            if nao_achados:
                avisar(f"Não encontrei na imagem: {', '.join(nao_achados)}")
    return salvar_nova_spec(alvo, partes, duracao_final, camera_final, pedido)


def salvar_nova_spec(alvo: AlvoCena, partes: list, duracao: float, camera: str, pedido: str = "") -> SpecCena:
    """Cria e grava os ajustes da cena (guarda o anterior em .json.bak)."""
    if alvo.spec.is_file():
        shutil.copy2(alvo.spec, alvo.spec.with_suffix(".json.bak"))
    spec = nova_spec(alvo.imagem, partes, duracao, camera, alvo.numero, caminho_relativo(alvo.imagem, alvo.spec))
    spec.observacao = f"pedido: {pedido}" if pedido else ""
    spec.salvar(alvo.spec)
    return spec


def caminho_relativo(destino: Path, arquivo_spec: Path) -> str:
    import os

    try:
        return Path(os.path.relpath(destino.resolve(), arquivo_spec.resolve().parent)).as_posix()
    except ValueError:
        return str(destino.resolve())


def renderizar_alvo(alvo: AlvoCena, spec: SpecCena, previa_rapida: bool = False,
                    mostrar_progresso: bool = True) -> tuple[Path, Path, dict[str, str]]:
    """Renderiza o MP4 da cena e a imagem de conferência das partes."""
    largura, altura = (960, 540) if previa_rapida else (config.LARGURA_VIDEO, config.ALTURA_VIDEO)
    audio_boca = alvo.audio if any("falar" in p.animacoes for p in spec.partes) else None
    renderizador = RenderizadorCena(spec, alvo.spec.parent, largura, altura, config.FPS, audio_boca=audio_boca)
    salvar_rgb(alvo.previa, renderizador.previa())
    inicio = time.monotonic()
    rotulo = alvo.imagem.stem

    interativo = mostrar_progresso and sys.stderr.isatty()

    def progresso(feitos: int, total: int) -> None:
        if interativo and (feitos == total or feitos % 15 == 0):
            sys.stderr.write(f"\rRenderizando {rotulo}: {100 * feitos // total:3d}%")
            sys.stderr.flush()

    renderizador.renderizar(alvo.video, progresso, preset="veryfast" if previa_rapida else "medium")
    if mostrar_progresso:
        sys.stderr.write(f"\rRenderizando {rotulo}: 100% ({time.monotonic() - inicio:.0f}s)\n")
        sys.stderr.flush()
    return alvo.video, alvo.previa, renderizador.modos_mascara
