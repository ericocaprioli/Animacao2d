"""Servidor local do editor visual (http://127.0.0.1:8765).

Serve a página do editor e uma pequena API JSON para listar cenas, salvar os
ajustes (caixas, pivôs, animações), localizar partes com a IA e renderizar.
"""

from __future__ import annotations

import json
import mimetypes
import threading
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from animacao2d import config
from animacao2d.animacao.catalogo import ANIMACOES, CAMERAS
from animacao2d.animacao.imagem import EXTENSOES, aviso_proporcao, salvar_rgb, tamanho_imagem
from animacao2d.animacao.render import RenderizadorCena
from animacao2d.animacao.spec import DIRECOES, MASCARAS, Camera, ErroSpec, SpecCena
from animacao2d.cenas import pedido_de_animacao
from animacao2d.animacao.detectar import partes_provisorias, pedido_manual_deteccao, resposta_manual_deteccao
from animacao2d.fluxo import AlvoCena, caminho_relativo, preparar_spec, renderizar_alvo, salvar_nova_spec
from animacao2d.llm import ClienteIA, ErroIA, criar_cliente, modo_ia
from animacao2d.projeto import Projeto
from animacao2d.util import nome_cena

PASTA_ESTATICA = Path(__file__).resolve().parent / "static"


class Editor:
    """Estado do editor: de onde vêm as cenas e como achar seus arquivos."""

    def __init__(self, projeto: Projeto | None = None, pasta_avulsa: Path | None = None):
        if projeto is None and pasta_avulsa is None:
            raise ValueError("Informe um projeto ou uma pasta de imagens.")
        self.projeto = projeto
        self.pasta = pasta_avulsa
        # grátis (copiar/colar no claude.ai) ou API
        self.manual = modo_ia() == "manual" or bool(
            projeto is not None and (projeto.dados.get("ia_manual") or projeto.dados.get("texto_manual")))
        self._ia: ClienteIA | None = None
        self._travas: dict[str, threading.Lock] = {}
        self._trava_geral = threading.Lock()

    # ------------------------------------------------------------ cenas

    def cenas(self) -> list[dict[str, Any]]:
        lista = []
        if self.projeto is not None:
            planejadas = {int(c["numero"]): c for c in self.projeto.cenas()}
            imagens = self.projeto.imagens()
            for n in sorted(set(planejadas) | set(imagens)):
                cena = planejadas.get(n, {})
                lista.append({
                    "id": nome_cena(n),
                    "rotulo": nome_cena(n),
                    "tem_imagem": n in imagens,
                    "tem_spec": self.projeto.spec_da_cena(n).is_file(),
                    "tem_video": self.projeto.video_da_cena(n).is_file(),
                    "duracao": cena.get("duracao"),
                    "descricao": cena.get("descricao", ""),
                    "narracao": cena.get("narracao", ""),
                    "pedido_planejado": pedido_de_animacao(cena),
                })
        else:
            for imagem in sorted(self.pasta.iterdir()):  # type: ignore[union-attr]
                if imagem.suffix.lower() in EXTENSOES and not imagem.stem.endswith("_partes"):
                    alvo = AlvoCena.avulso(imagem)
                    lista.append({"id": imagem.stem, "rotulo": imagem.name, "tem_imagem": True,
                                  "tem_spec": alvo.spec.is_file(), "tem_video": alvo.video.is_file(),
                                  "duracao": None, "descricao": "", "narracao": "", "pedido_planejado": ""})
        return lista

    def alvo(self, identificador: str) -> AlvoCena:
        if self.projeto is not None:
            from animacao2d.util import numero_cena

            return AlvoCena.do_projeto(self.projeto, numero_cena(identificador))
        for imagem in self.pasta.iterdir():  # type: ignore[union-attr]
            if imagem.stem == identificador and imagem.suffix.lower() in EXTENSOES:
                return AlvoCena.avulso(imagem)
        raise FileNotFoundError(f"Cena '{identificador}' não encontrada.")

    def trava(self, identificador: str) -> threading.Lock:
        with self._trava_geral:
            return self._travas.setdefault(identificador, threading.Lock())

    def ia(self) -> ClienteIA:
        if self._ia is None:
            self._ia = criar_cliente()
        return self._ia

    # ------------------------------------------------------------ dados de uma cena

    def dados_cena(self, identificador: str) -> dict[str, Any]:
        alvo = self.alvo(identificador)
        largura, altura = tamanho_imagem(alvo.imagem)
        provisorio = False
        if alvo.spec.is_file():
            spec = SpecCena.carregar(alvo.spec)
            spec.ajustar_tamanho(largura, altura)
            salvo = True
        else:
            planejada = alvo.planejada or {}
            spec = SpecCena(imagem=alvo.imagem.name, largura=largura, altura=altura,
                            duracao=float(planejada.get("duracao") or 5.0),
                            camera=Camera(movimento=planejada.get("camera") or "zoom_in"), cena=alvo.numero)
            pedido = pedido_de_animacao(planejada)
            if pedido:  # já traz as partes planejadas como caixas para arrastar até o lugar certo
                spec.partes = partes_provisorias(pedido, largura, altura)
                provisorio = True
            salvo = False
        return {
            "id": identificador,
            "spec": spec.para_dict(),
            "salvo": salvo,
            "provisorio": provisorio,
            "largura": largura,
            "altura": altura,
            "imagem_url": f"/arquivo/imagem/{identificador}?v={int(alvo.imagem.stat().st_mtime)}",
            "video_url": (f"/arquivo/video/{identificador}?v={int(alvo.video.stat().st_mtime)}"
                          if alvo.video.is_file() else None),
            "pedido_planejado": pedido_de_animacao(alvo.planejada or {}),
            "descricao": (alvo.planejada or {}).get("descricao", ""),
            "narracao": (alvo.planejada or {}).get("narracao", ""),
            "aviso": aviso_proporcao(largura, altura, alvo.imagem.name),
        }

    def salvar_spec(self, identificador: str, dados: dict) -> SpecCena:
        alvo = self.alvo(identificador)
        spec = SpecCena.de_dict(dados)
        spec.imagem = caminho_relativo(alvo.imagem, alvo.spec)
        largura, altura = tamanho_imagem(alvo.imagem)
        spec.largura, spec.altura = largura, altura
        spec.salvar(alvo.spec)
        return spec


def catalogo() -> dict[str, Any]:
    return {
        "animacoes": [{"nome": n, "categoria": t.categoria, "descricao": t.descricao, "exemplos": t.exemplos}
                      for n, t in ANIMACOES.items()],
        "cameras": [{"nome": n, "descricao": d} for n, d in CAMERAS.items()],
        "mascaras": list(MASCARAS),
        "direcoes": [d for d in DIRECOES if d],
    }


def criar_tratador(editor: Editor):
    class Tratador(BaseHTTPRequestHandler):
        server_version = "Animacao2dEditor/1"

        def log_message(self, formato, *args):  # silencioso
            pass

        # ---------------------------------------------------- respostas

        def _json(self, dados: Any, status: int = 200) -> None:
            corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(corpo)

        def _erro(self, mensagem: str, status: int = 400) -> None:
            self._json({"erro": mensagem}, status)

        def _arquivo(self, caminho: Path) -> None:
            if not caminho.is_file():
                self._erro("arquivo não encontrado", 404)
                return
            tipo = mimetypes.guess_type(caminho.name)[0] or "application/octet-stream"
            tamanho = caminho.stat().st_size
            inicio, fim = 0, tamanho - 1
            faixa = self.headers.get("Range")
            status = HTTPStatus.OK
            if faixa and faixa.startswith("bytes="):
                a, _, b = faixa[6:].partition("-")
                inicio = int(a) if a else max(0, tamanho - int(b))
                fim = int(b) if (a and b) else tamanho - 1
                fim = min(fim, tamanho - 1)
                status = HTTPStatus.PARTIAL_CONTENT
            self.send_response(status)
            self.send_header("Content-Type", tipo)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(fim - inicio + 1))
            self.send_header("Cache-Control", "no-store")
            if status == HTTPStatus.PARTIAL_CONTENT:
                self.send_header("Content-Range", f"bytes {inicio}-{fim}/{tamanho}")
            self.end_headers()
            with open(caminho, "rb") as arquivo:
                arquivo.seek(inicio)
                restante = fim - inicio + 1
                while restante > 0:
                    bloco = arquivo.read(min(1 << 16, restante))
                    if not bloco:
                        break
                    self.wfile.write(bloco)
                    restante -= len(bloco)

        def _corpo(self) -> dict:
            tamanho = int(self.headers.get("Content-Length", 0) or 0)
            if not tamanho:
                return {}
            return json.loads(self.rfile.read(tamanho).decode("utf-8"))

        # ---------------------------------------------------- rotas

        def do_GET(self):  # noqa: N802
            caminho = unquote(urlparse(self.path).path)
            try:
                if caminho in ("/", "/index.html"):
                    self._arquivo(PASTA_ESTATICA / "editor.html")
                elif caminho == "/api/estado":
                    titulo = editor.projeto.titulo if editor.projeto else str(editor.pasta)
                    self._json({"modo": "projeto" if editor.projeto else "pasta", "titulo": titulo,
                                "modo_ia": "manual" if editor.manual else "api",
                                "cenas": editor.cenas(), "catalogo": catalogo()})
                elif caminho.startswith("/api/cena/"):
                    self._json(editor.dados_cena(caminho.split("/")[3]))
                elif caminho.startswith("/arquivo/"):
                    _, _, tipo, identificador = caminho.split("/", 3)
                    alvo = editor.alvo(identificador)
                    arquivos = {"imagem": alvo.imagem, "video": alvo.video, "previa": alvo.previa,
                                "mascaras": alvo.previa.with_name(alvo.previa.stem + "_mascaras.png")}
                    if tipo not in arquivos:
                        self._erro("tipo de arquivo inválido", 404)
                    else:
                        self._arquivo(arquivos[tipo])
                else:
                    self._erro("rota não encontrada", 404)
            except (FileNotFoundError, ValueError, ErroSpec) as erro:
                self._erro(str(erro), 404)
            except Exception as erro:  # noqa: BLE001
                traceback.print_exc()
                self._erro(f"erro interno: {erro}", 500)

        def do_POST(self):  # noqa: N802
            caminho = unquote(urlparse(self.path).path)
            partes = caminho.strip("/").split("/")
            try:
                if len(partes) < 3 or partes[:2] != ["api", "cena"]:
                    self._erro("rota não encontrada", 404)
                    return
                identificador = partes[2]
                acao = partes[3] if len(partes) > 3 else "salvar"
                corpo = self._corpo()
                with editor.trava(identificador):
                    if acao == "salvar":
                        editor.salvar_spec(identificador, corpo["spec"])
                        self._json({"ok": True})
                    elif acao == "pedido_manual":
                        alvo = editor.alvo(identificador)
                        pedido = (corpo.get("pedido") or "").strip() or pedido_de_animacao(alvo.planejada or {})
                        if not pedido:
                            self._erro("Escreva o que animar (ex.: braço, olho, sol).")
                            return
                        contexto = (alvo.planejada or {}).get("descricao", "")
                        self._json({"ok": True, "texto": pedido_manual_deteccao(alvo.imagem, pedido, contexto)})
                    elif acao == "resposta_manual":
                        alvo = editor.alvo(identificador)
                        partes, nao_achados, camera = resposta_manual_deteccao(corpo.get("texto", ""), alvo.imagem)
                        if not partes:
                            self._erro("A resposta não trouxe nenhuma parte. Confira se a imagem foi anexada.")
                            return
                        planejada = alvo.planejada or {}
                        duracao = float(corpo.get("duracao") or planejada.get("duracao") or 5.0)
                        spec = salvar_nova_spec(alvo, partes, duracao, planejada.get("camera") or camera,
                                                (corpo.get("pedido") or "").strip())
                        self._json({"ok": True, "spec": spec.para_dict(), "nao_encontrados": nao_achados})
                    elif acao == "detectar":
                        if editor.manual:
                            self._erro("Modo grátis: use Copiar imagem / Copiar pedido e cole a resposta do claude.ai.")
                            return
                        alvo = editor.alvo(identificador)
                        pedido = (corpo.get("pedido") or "").strip() or pedido_de_animacao(alvo.planejada or {})
                        if not pedido:
                            self._erro("Escreva o que animar (ex.: braço, olho, sol).")
                            return
                        spec = preparar_spec(alvo, editor.ia(), pedido, duracao=corpo.get("duracao"),
                                             redetectar=True, avisar=lambda *_: None)
                        self._json({"ok": True, "spec": spec.para_dict()})
                    elif acao == "renderizar":
                        if corpo.get("spec"):
                            editor.salvar_spec(identificador, corpo["spec"])
                        alvo = editor.alvo(identificador)
                        spec = SpecCena.carregar(alvo.spec)
                        _, _, modos = renderizar_alvo(alvo, spec, previa_rapida=bool(corpo.get("previa", True)),
                                                      mostrar_progresso=False)
                        falhas = [n for n, m in modos.items() if m != "auto"]
                        self._json({"ok": True, "falhas_recorte": falhas,
                                    "video_url": f"/arquivo/video/{identificador}?v={int(alvo.video.stat().st_mtime)}"})
                    elif acao == "mascaras":
                        alvo = editor.alvo(identificador)
                        spec = SpecCena.de_dict(corpo["spec"])
                        spec.imagem = str(alvo.imagem.resolve())
                        renderizador = RenderizadorCena(spec, alvo.imagem.parent, 960, 540, config.FPS)
                        destino = alvo.previa.with_name(alvo.previa.stem + "_mascaras.png")
                        salvar_rgb(destino, renderizador.previa(com_rotulos=False))
                        self._json({"ok": True, "url": f"/arquivo/mascaras/{identificador}?v={destino.stat().st_mtime_ns}",
                                    "modos": renderizador.modos_mascara})
                    else:
                        self._erro("ação desconhecida", 404)
            except (ErroIA, ErroSpec, FileNotFoundError, ValueError, KeyError) as erro:
                self._erro(str(erro))
            except Exception as erro:  # noqa: BLE001
                traceback.print_exc()
                self._erro(f"erro interno: {erro}", 500)

    return Tratador


def iniciar(projeto: Projeto | None = None, pasta_avulsa: Path | None = None, porta: int = 8765,
            abrir: bool = True) -> int:
    editor = Editor(projeto, pasta_avulsa)
    try:
        servidor = ThreadingHTTPServer(("127.0.0.1", porta), criar_tratador(editor))
    except OSError:
        servidor = ThreadingHTTPServer(("127.0.0.1", 0), criar_tratador(editor))
    endereco = f"http://127.0.0.1:{servidor.server_address[1]}/"
    print(f"Editor aberto em {endereco}  (Ctrl+C para fechar)")
    if abrir:
        threading.Timer(0.6, lambda: webbrowser.open(endereco)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEditor fechado.")
    finally:
        servidor.server_close()
    return 0
