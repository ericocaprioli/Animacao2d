"""Linha de comando: animacao2d <comando> ...

Fluxo típico:
    animacao2d novo "como funciona a internet"   # títulos -> aprovação -> roteiro -> aprovação -> cenas
    (gere as imagens e salve em projetos/<video>/imagens/cena01.png, cena02.png, ...)
    animacao2d animar cena01 "braço, olho, sol"  # anima as partes pedidas
    animacao2d animar --todas                    # anima todas as cenas com a lista planejada
    animacao2d editor                            # ajusta caixas/pivôs no navegador
    animacao2d montar --audio narracao.mp3       # vídeo completo
"""

from __future__ import annotations

import argparse
import traceback
from pathlib import Path

from animacao2d import __version__, config
from animacao2d.animacao.catalogo import ANIMACOES, CAMERAS, resolver_camera
from animacao2d.animacao.imagem import EXTENSOES
from animacao2d.animacao.spec import ErroSpec
from animacao2d.llm import ClienteIA, ErroIA, criar_cliente, modo_ia
from animacao2d.projeto import ErroProjeto, Projeto
from animacao2d.roteiro import palavras_alvo
from animacao2d.util import (configurar_console, formatar_tempo, nome_cena, numero_cena, perguntar, salvar_json,
                             slugify)


def _ia(args, pasta: Path | str = ".", projeto: Projeto | None = None) -> ClienteIA:
    """Manual (grátis, copiar/colar no claude.ai) ou API: --manual/--api, o projeto ou o .env decidem."""
    manual = modo_ia() == "manual"
    if projeto is not None and (projeto.dados.get("ia_manual") or projeto.dados.get("texto_manual")):
        manual = True
    if getattr(args, "manual", False):
        manual = True
    if getattr(args, "api", False):
        manual = False
    return criar_cliente(manual=manual, pasta=pasta)


def _faixas(numeros: list[int]) -> str:
    """[1,2,3,5,7,8] -> 'cena01-03, cena05, cena07-08'."""
    if not numeros:
        return "-"
    partes, inicio, anterior = [], numeros[0], numeros[0]
    for n in numeros[1:] + [None]:  # type: ignore[list-item]
        if n is not None and n == anterior + 1:
            anterior = n
            continue
        partes.append(nome_cena(inicio) if inicio == anterior else f"{nome_cena(inicio)}-{anterior:02d}")
        if n is not None:
            inicio = anterior = n
    return ", ".join(partes)


# ---------------------------------------------------------------- títulos / roteiro / cenas


def _escolher_titulo(ia: ClienteIA, tema: str, quantidade: int) -> tuple[str, list[dict]]:
    from animacao2d.roteiro import sugerir_titulos

    while True:
        titulos = sugerir_titulos(ia, tema, quantidade)
        print(f"\nTítulos para: {tema}\n")
        for i, t in enumerate(titulos, 1):
            print(f" {i:2d}. {t['titulo']}")
            print(f"     ângulo: {t['angulo']}")
            print(f"     gancho: {t['gancho']}")
            print(f"     thumbnail: {t['thumbnail']}\n")
        resposta = ""
        while not resposta:  # Enter vazio (ou linha em branco colada) não escolhe nada
            resposta = perguntar("Escolha o número do título, digite um título seu, 'r' para gerar outros ou "
                                 "'s' para sair: ")
        if resposta.lower() == "s":
            raise KeyboardInterrupt
        if resposta.lower() == "r":
            continue
        if resposta.isdigit() and 1 <= int(resposta) <= len(titulos):
            return titulos[int(resposta) - 1]["titulo"], titulos
        return resposta, titulos


def _aprovar_roteiro(projeto: Projeto, ia: ClienteIA) -> bool:
    from animacao2d.fluxo import carregar_roteiro, gerar_roteiro, salvar_roteiro

    while True:
        roteiro = carregar_roteiro(projeto)
        ppm = float(projeto.dados.get("palavras_por_minuto", config.PALAVRAS_POR_MINUTO))
        alvo = palavras_alvo(float(projeto.dados.get("minutos", config.MINUTOS_PADRAO)), ppm)
        print(f"\nRoteiro: {projeto.roteiro_md}\n  {roteiro.resumo(ppm)} (alvo: ~{alvo} palavras)")
        if not 0.85 * alvo <= roteiro.palavras <= 1.15 * alvo:
            acao = "expandir" if roteiro.palavras < alvo else "enxugar"
            print(f"  Atenção: tamanho fora do alvo. Use [r] e peça para {acao} até ~{alvo} palavras.")
        for s in roteiro.secoes:
            print(f"  - [{s.tipo}] {s.titulo}")
        print("\n  [a] aprovar e gerar as cenas   [r] reescrever com um pedido   "
              "[e] editei o roteiro.md, recarregar   [s] sair e continuar depois")
        opcao = ""
        while opcao not in ("a", "r", "e", "s"):  # exige uma escolha explícita
            opcao = perguntar("Opção (a/r/e/s): ").lower()
        if opcao == "a":
            salvar_roteiro(projeto, roteiro)
            projeto.definir_etapa("roteiro_aprovado")
            return True
        if opcao == "r":
            pedido = ""
            while not pedido:
                pedido = perguntar("O que mudar? ")
            gerar_roteiro(projeto, ia, pedido, partir_do_atual=True)
        elif opcao == "s":
            print(f"Tudo salvo. Para continuar: animacao2d roteiro -p {projeto.pasta}  |  animacao2d cenas -p {projeto.pasta}")
            return False


def _resumo_cenas(plano: dict, projeto: Projeto) -> None:
    cenas = plano["cenas"]
    media = plano["duracao_total"] / max(1, len(cenas))
    print(f"\n{len(cenas)} cenas, duração estimada {formatar_tempo(plano['duracao_total'])} "
          f"(média {media:.1f} s por cena, ritmo {plano['ritmo']}).")
    print("Arquivos:")
    for caminho in (projeto.cenas_md, projeto.prompts_txt, projeto.prompts_csv, projeto.animacoes_md,
                    projeto.narracao_md, projeto.legendas_srt):
        print(f"  - {caminho}")
    print(f"\nPróximo passo: gere as imagens e salve em {projeto.pasta_imagens}/cena01.png, cena02.png, ...")
    print("Depois: animacao2d animar cena01   (ou animacao2d animar --todas)")


def cmd_novo(args) -> int:
    ia = _ia(args, config.pasta_projetos() / "_novo")
    titulo, sugestoes = (args.titulo, []) if args.titulo else _escolher_titulo(ia, args.tema, args.quantidade)
    projeto = Projeto.criar(titulo, args.tema, minutos=args.minutos, ritmo=args.ritmo)
    projeto.dados["ia_manual"] = ia.nome == "manual"
    projeto.salvar()
    if sugestoes:
        salvar_json(projeto.titulos_json, {"tema": args.tema, "escolhido": titulo, "titulos": sugestoes})
    print(f"\nProjeto criado: {projeto.pasta}")
    if ia.nome == "manual":
        ia = _ia(args, projeto.pasta, projeto)
    from animacao2d.fluxo import gerar_plano_de_cenas, gerar_roteiro

    gerar_roteiro(projeto, ia)
    if not _aprovar_roteiro(projeto, ia):
        return 0
    plano = gerar_plano_de_cenas(projeto, ia, args.ritmo, args.paralelo)
    _resumo_cenas(plano, projeto)
    return 0


def cmd_titulos(args) -> int:
    from animacao2d.roteiro import sugerir_titulos

    pasta = config.pasta_projetos() / "_titulos"
    titulos = sugerir_titulos(_ia(args, pasta), args.tema, args.quantidade)
    for i, t in enumerate(titulos, 1):
        print(f"{i:2d}. {t['titulo']}\n    ângulo: {t['angulo']}\n    gancho: {t['gancho']}\n"
              f"    thumbnail: {t['thumbnail']}\n")
    destino = pasta / f"{slugify(args.tema)}.json"
    salvar_json(destino, {"tema": args.tema, "titulos": titulos})
    print(f"Salvo em {destino}. Para seguir: animacao2d novo \"{args.tema}\" --titulo \"<título escolhido>\"")
    return 0


def cmd_roteiro(args) -> int:
    from animacao2d.fluxo import gerar_roteiro

    projeto = Projeto.resolver(args.projeto)
    ia = _ia(args, projeto.pasta, projeto)
    if args.titulo:
        projeto.dados["titulo"] = args.titulo
        projeto.salvar()
    gerar_roteiro(projeto, ia, args.pedido or "", partir_do_atual=bool(args.pedido) and projeto.roteiro_md.is_file())
    if _aprovar_roteiro(projeto, ia) and perguntar("Gerar as cenas agora? [S/n] ", "s").lower().startswith("s"):
        return cmd_cenas(args)
    return 0


def cmd_cenas(args) -> int:
    from animacao2d.fluxo import gerar_plano_de_cenas

    projeto = Projeto.resolver(args.projeto)
    imagens = projeto.imagens()
    if imagens and projeto.cenas_json.is_file() and not getattr(args, "forcar", False):
        print(f"Já existem {len(imagens)} imagens em {projeto.pasta_imagens}. Gerar as cenas de novo muda a "
              "numeração e os prompts. Use --forcar se tiver certeza.")
        return 1
    if projeto.dados.get("etapa") in ("roteiro", "titulo_aprovado"):
        print("Obs.: usando o roteiro.md atual como aprovado.")
    plano = gerar_plano_de_cenas(projeto, _ia(args, projeto.pasta, projeto), getattr(args, "ritmo", None),
                                 getattr(args, "paralelo", 1))
    _resumo_cenas(plano, projeto)
    return 0


def cmd_exportar(args) -> int:
    from animacao2d.fluxo import exportar_arquivos

    projeto = Projeto.resolver(args.projeto)
    for caminho in exportar_arquivos(projeto):
        print(f"  - {caminho}")
    return 0


# ---------------------------------------------------------------- animar


def cmd_animar(args) -> int:
    from animacao2d.fluxo import AlvoCena, preparar_spec, renderizar_alvo

    camera = resolver_camera(args.camera) if args.camera else None
    alvos: list[AlvoCena] = []
    pasta_ia: Path = Path(".")
    projeto_ia: Projeto | None = None
    if args.alvo and Path(args.alvo).suffix.lower() in EXTENSOES:
        imagem = Path(args.alvo)
        if not imagem.is_file():
            print(f"Imagem não encontrada: {imagem}")
            return 1
        alvos.append(AlvoCena.avulso(imagem))
        pasta_ia = imagem.parent
    else:
        projeto = Projeto.resolver(args.projeto)
        pasta_ia, projeto_ia = projeto.pasta, projeto
        if args.todas:
            numeros = sorted(projeto.imagens())
            if not numeros:
                print(f"Nenhuma imagem em {projeto.pasta_imagens} (nomeie como cena01.png, cena02.png...).")
                return 1
        elif args.alvo:
            numeros = [numero_cena(args.alvo)]
        else:
            print("Diga qual cena animar (ex.: animacao2d animar cena01 \"braço, olho\") ou use --todas.")
            return 1
        for n in numeros:
            try:
                alvos.append(AlvoCena.do_projeto(projeto, n))
            except FileNotFoundError as erro:
                print(erro)
                if not args.todas:
                    return 1
        if args.todas and not args.forcar:
            antes = len(alvos)
            alvos = [a for a in alvos if not _video_atualizado(a)]
            if antes != len(alvos):
                print(f"{antes - len(alvos)} cena(s) já animadas e sem mudanças foram puladas (use --forcar para refazer).")

    ia = None
    precisa_ia = not args.sem_ia and any(
        (args.pedido or args.redetectar or not a.spec.is_file()) and (args.pedido or (a.planejada or {}).get("animacoes"))
        for a in alvos)
    if precisa_ia:
        try:
            ia = _ia(args, pasta_ia, projeto_ia)
        except ErroIA as erro:
            print(f"{erro}\nContinuando sem IA (caixas provisórias).")
    falhas = []
    for i, alvo in enumerate(alvos, 1):
        rotulo = alvo.imagem.stem
        if len(alvos) > 1:
            print(f"\n[{i}/{len(alvos)}] {rotulo}")
        try:
            spec = preparar_spec(alvo, ia, args.pedido or "", args.duracao, camera, args.redetectar,
                                 args.sem_ia or ia is None)
            video, previa, modos = renderizar_alvo(alvo, spec, previa_rapida=args.previa)
            partes = ", ".join(f"{p.nome} ({'+'.join(p.animacoes)})" for p in spec.partes) or "só câmera"
            print(f"  partes: {partes}\n  câmera: {spec.camera.movimento}, {spec.duracao:.1f} s")
            ruins = [nome for nome, modo in modos.items() if modo != "auto"]
            if ruins:
                print(f"  recorte automático falhou em: {', '.join(ruins)} (usei caixa/elipse). "
                      f"Confira em {previa} ou ajuste no editor.")
            print(f"  vídeo: {video}\n  conferência das partes: {previa}\n  ajustes: {alvo.spec}")
        except (ErroIA, ErroSpec, FileNotFoundError, ValueError) as erro:
            print(f"  erro em {rotulo}: {erro}")
            falhas.append(rotulo)
            if len(alvos) == 1:
                return 1
    if falhas:
        print(f"\nCenas com erro: {', '.join(falhas)}")
    return 1 if falhas else 0


def _video_atualizado(alvo) -> bool:
    if not alvo.video.is_file():
        return False
    referencia = max(alvo.imagem.stat().st_mtime, alvo.spec.stat().st_mtime if alvo.spec.is_file() else 0)
    return alvo.video.stat().st_mtime >= referencia


# ---------------------------------------------------------------- outros


def cmd_editor(args) -> int:
    from animacao2d.editor.servidor import iniciar

    alvo = args.alvo
    if alvo and Path(alvo).is_dir() and not (Path(alvo) / "projeto.json").is_file():
        return iniciar(pasta_avulsa=Path(alvo), porta=args.porta, abrir=not args.nao_abrir)
    projeto = Projeto.resolver(alvo or args.projeto)
    return iniciar(projeto=projeto, porta=args.porta, abrir=not args.nao_abrir)


def cmd_montar(args) -> int:
    from animacao2d.montagem import montar_video

    projeto = Projeto.resolver(args.projeto)
    destino = montar_video(projeto, args.saida, args.audio, args.previa)
    print(f"Vídeo montado: {destino}")
    return 0


def cmd_status(args) -> int:
    from animacao2d.fluxo import carregar_roteiro

    projeto = Projeto.resolver(args.projeto)
    print(f"Projeto: {projeto.titulo}\nPasta: {projeto.pasta}\nEtapa: {projeto.dados.get('etapa')}")
    if projeto.roteiro_md.is_file():
        try:
            ppm = float(projeto.dados.get("palavras_por_minuto", config.PALAVRAS_POR_MINUTO))
            print(f"Roteiro: {carregar_roteiro(projeto).resumo(ppm)}")
        except ValueError as erro:
            print(f"Roteiro: {erro}")
    cenas = projeto.cenas()
    if cenas:
        numeros = [int(c["numero"]) for c in cenas]
        imagens = projeto.imagens()
        animadas = [n for n in numeros if projeto.video_da_cena(n).is_file()]
        sem_imagem = [n for n in numeros if n not in imagens]
        total = sum(float(c["duracao"]) for c in cenas)
        print(f"Cenas: {len(cenas)} ({formatar_tempo(total)})")
        print(f"Imagens: {len(numeros) - len(sem_imagem)}/{len(numeros)}"
              + (f"  faltando: {_faixas(sem_imagem)}" if sem_imagem else ""))
        print(f"Animadas: {len(animadas)}/{len(numeros)}")
        audios = projeto.audios()
        if audios:
            print(f"Áudios por cena: {len(audios)}")
    return 0


def cmd_animacoes(args) -> int:
    print("Animações (use em 'animar': elemento:animacao, ex.: \"braço:acenar, sol:girar+pulsar\"):\n")
    for nome, tipo in ANIMACOES.items():
        print(f"  {nome:10s} {tipo.descricao}\n  {'':10s} bom para: {tipo.exemplos}")
    print("\nCâmeras (--camera):\n")
    for nome, descricao in CAMERAS.items():
        print(f"  {nome:13s} {descricao}")
    print("\nRitmos (--ritmo):\n")
    for nome, ritmo in config.RITMOS.items():
        print(f"  {nome:7s} {ritmo.descricao}")
    return 0


def cmd_exemplo(args) -> int:
    """Renderiza a cena de exemplo que vem com o projeto (não precisa de IA)."""
    from animacao2d.exemplo import SPEC_EXEMPLO, desenhar
    from animacao2d.fluxo import AlvoCena, preparar_spec, renderizar_alvo

    pasta = Path(args.pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    imagem, spec = pasta / "cena01.png", pasta / "cena01.json"
    if not imagem.is_file():
        desenhar().save(imagem)
    if not spec.is_file():
        salvar_json(spec, SPEC_EXEMPLO)
    alvo = AlvoCena.avulso(imagem)
    video, previa, _ = renderizar_alvo(alvo, preparar_spec(alvo, None, sem_ia=True), previa_rapida=args.previa)
    print(f"Pronto! Vídeo: {video}\nPartes: {previa}\nAjustes: {alvo.spec}")
    return 0


# ---------------------------------------------------------------- argparse


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="animacao2d", description="Roteiro, cenas e animações 2D para vídeos "
                                "explicativos no estilo Crayon Capital.")
    p.add_argument("--versao", action="version", version=f"animacao2d {__version__}")
    sub = p.add_subparsers(dest="comando", metavar="comando")

    def com_projeto(sp):
        sp.add_argument("-p", "--projeto", help="pasta ou nome do projeto (padrão: o último usado)")

    def com_manual(sp):
        sp.add_argument("--manual", action="store_true",
                        help="sem API: você cola o pedido no claude.ai e cola a resposta de volta")
        sp.add_argument("--api", action="store_true",
                        help="usa a API mesmo se o projeto/.env estiver em modo manual")

    s = sub.add_parser("novo", help="tema -> títulos -> roteiro -> cenas (fluxo guiado)")
    s.add_argument("tema")
    s.add_argument("--titulo", help="pula a sugestão e usa este título")
    s.add_argument("--minutos", type=float, default=config.MINUTOS_PADRAO)
    s.add_argument("--ritmo", choices=list(config.RITMOS), default=config.RITMO_PADRAO)
    s.add_argument("-n", "--quantidade", type=int, default=8, help="quantos títulos sugerir")
    s.add_argument("--paralelo", type=int, default=1, help="seções geradas ao mesmo tempo (mais rápido)")
    com_manual(s)
    s.set_defaults(funcao=cmd_novo)

    s = sub.add_parser("titulos", help="só sugere títulos para um tema")
    s.add_argument("tema")
    s.add_argument("-n", "--quantidade", type=int, default=8)
    com_manual(s)
    s.set_defaults(funcao=cmd_titulos)

    s = sub.add_parser("roteiro", help="escreve ou reescreve o roteiro do projeto")
    com_projeto(s)
    s.add_argument("--pedido", help="o que mudar (reescreve a partir do roteiro atual)")
    s.add_argument("--titulo", help="troca o título do projeto antes de escrever")
    s.add_argument("--ritmo", choices=list(config.RITMOS))
    s.add_argument("--paralelo", type=int, default=1)
    com_manual(s)
    s.set_defaults(funcao=cmd_roteiro)

    s = sub.add_parser("cenas", help="gera prompts das cenas e a lista de animações")
    com_projeto(s)
    s.add_argument("--ritmo", choices=list(config.RITMOS))
    s.add_argument("--paralelo", type=int, default=1)
    s.add_argument("--forcar", action="store_true", help="gera de novo mesmo com imagens já criadas")
    com_manual(s)
    s.set_defaults(funcao=cmd_cenas)

    s = sub.add_parser("exportar", help="refaz cenas.md, prompts.txt etc. a partir de cenas.json/estilo")
    com_projeto(s)
    s.set_defaults(funcao=cmd_exportar)

    s = sub.add_parser("animar", help="anima uma cena: animacao2d animar cena01 \"braço, olho, sol\"")
    s.add_argument("alvo", nargs="?", help="cena (cena01, 1) ou caminho de uma imagem")
    s.add_argument("pedido", nargs="?", help="o que animar: \"braço, olho, sol\" ou \"braço:acenar, sol:girar\"")
    com_projeto(s)
    s.add_argument("--todas", action="store_true", help="anima todas as cenas que já têm imagem")
    s.add_argument("--duracao", type=float, help="duração em segundos")
    s.add_argument("--camera", help=f"movimento de câmera: {', '.join(CAMERAS)}")
    s.add_argument("--redetectar", action="store_true", help="localiza as partes de novo com a IA")
    s.add_argument("--sem-ia", action="store_true", help="não usa IA: cria caixas para ajustar no editor")
    s.add_argument("--previa", action="store_true", help="vídeo menor e mais rápido, para conferir")
    s.add_argument("--forcar", action="store_true", help="com --todas, refaz até as já animadas")
    com_manual(s)
    s.set_defaults(funcao=cmd_animar)

    s = sub.add_parser("editor", help="abre o editor visual no navegador")
    s.add_argument("alvo", nargs="?", help="projeto ou pasta com imagens avulsas")
    com_projeto(s)
    s.add_argument("--porta", type=int, default=8765)
    s.add_argument("--nao-abrir", action="store_true", help="não abre o navegador sozinho")
    s.set_defaults(funcao=cmd_editor)

    s = sub.add_parser("montar", help="monta o vídeo completo com todas as cenas")
    com_projeto(s)
    s.add_argument("--audio", help="narração completa (as cenas se ajustam à duração dela)")
    s.add_argument("--saida", help="arquivo de saída (padrão: video/video_completo.mp4)")
    s.add_argument("--previa", action="store_true", help="versão 960x540 rápida")
    s.set_defaults(funcao=cmd_montar)

    s = sub.add_parser("status", help="mostra o andamento do projeto")
    com_projeto(s)
    s.set_defaults(funcao=cmd_status)

    s = sub.add_parser("animacoes", help="lista animações, câmeras e ritmos disponíveis")
    s.set_defaults(funcao=cmd_animacoes)

    s = sub.add_parser("exemplo", help="gera o vídeo de exemplo (sem IA) para testar a instalação")
    s.add_argument("--pasta", default="exemplo_animacao2d")
    s.add_argument("--previa", action="store_true")
    s.set_defaults(funcao=cmd_exemplo)
    return p


def main(argv: list[str] | None = None) -> int:
    configurar_console()
    config.carregar_env()
    parser = _parser()
    args = parser.parse_args(argv)
    if not getattr(args, "funcao", None):
        parser.print_help()
        return 0
    try:
        return int(args.funcao(args) or 0)
    except KeyboardInterrupt:
        print("\nInterrompido.")
        return 130
    except BrokenPipeError:  # saída cortada (ex.: | head)
        return 0
    except (ErroIA, ErroProjeto, ErroSpec, FileNotFoundError, ValueError) as erro:
        print(f"Erro: {erro}")
        return 1
    except Exception:  # noqa: BLE001 - mostra o rastro para facilitar reportar bugs
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
