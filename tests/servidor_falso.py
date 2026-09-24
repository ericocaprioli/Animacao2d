"""Servidor HTTP local que imita a API de mensagens da Anthropic (streaming SSE).

Responde conforme a etapa (títulos, roteiro, cenas, localização de partes),
para testar a linha de comando de ponta a ponta sem gastar créditos.
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from api_falsa import _sse

PARAGRAFO = ("A internet parece mágica, mas é só um monte de computadores trocando cartinhas muito rápido. "
             "Cada cartinha leva um endereço, igual carta de correio, e passa de mão em mão até chegar. ")


def resposta_titulos(_: dict) -> dict:
    return {"titulos": [
        {"titulo": "A Internet Explicada Como Se Você Tivesse 5 Anos", "angulo": "explicação",
         "gancho": "Toda vez que você abre um vídeo, milhões de cartinhas atravessam o mundo.",
         "thumbnail": "planeta com cabos e um carteiro desesperado"},
        {"titulo": "Como a Internet Realmente Funciona", "angulo": "mistério",
         "gancho": "Ninguém é dono da internet. E mesmo assim ela quase nunca cai.",
         "thumbnail": "cabo submarino com tubarão mordendo"},
    ]}


def resposta_roteiro(pedido: dict) -> dict:
    texto = pedido["messages"][0]["content"][0]["text"]
    alvo = int(re.search(r"cerca de (\d+) palavras", texto).group(1))
    palavras_por_secao = max(40, alvo // 4)
    repeticoes = max(1, palavras_por_secao // len(PARAGRAFO.split()))
    corpo = (PARAGRAFO * repeticoes).strip()
    return {
        "titulo": "A Internet Explicada Como Se Você Tivesse 5 Anos",
        "descricao": "Como seus vídeos chegam até você.",
        "personagens": [
            {"tag": "DEV", "nome": "Dev", "papel": "programador curioso",
             "descricao_visual": "a young developer with a bean-shaped head, messy black hair and a green hoodie"},
            {"tag": "ROTEADOR", "nome": "Roteador", "papel": "carteiro da internet",
             "descricao_visual": "a small router character with blinking antennas and a mail bag"},
        ],
        "secoes": [
            {"titulo": "Gancho", "tipo": "gancho", "texto": corpo},
            {"titulo": "O endereço", "tipo": "capitulo",
             "texto": corpo + "\n\nDEV: Espera, então cada site tem um endereço?\n\nROTEADOR: Tem. E eu decoro todos."},
            {"titulo": "Os pacotes", "tipo": "capitulo", "texto": corpo},
            {"titulo": "Conclusão", "tipo": "conclusao", "texto": corpo},
        ],
    }


def resposta_cenas(pedido: dict) -> dict:
    texto = pedido["messages"][0]["content"][-1]["text"]
    total = int(re.search(r"\((\d+) no total", texto).group(1))
    cenas = []
    for inicio in range(1, total + 1, 2):
        cenas.append({
            "inicio": inicio, "fim": min(total, inicio + 1), "plano": "medio",
            "descricao": "O Dev olha o roteador entregando cartas.",
            "expressao": "surpresa exagerada do DEV",
            "prompt": "[DEV] stares at [ROTEADOR] with eyes wide as plates, jaw dropped, waving his right arm",
            "animacoes": [{"elemento": "braço direito do DEV", "animacao": "acenar"},
                          {"elemento": "olhos do DEV", "animacao": "piscar"}],
            "camera": "zoom_in", "texto_na_tela": "",
        })
    return {"cenas": cenas}


def resposta_deteccao(_: dict) -> dict:
    # coordenadas da cena de exemplo (animacao2d.exemplo)
    return {"partes": [
        {"nome": "braço direito do DEV", "animacoes": ["acenar"], "caixa": [348, 190, 478, 385],
         "pivo": [462, 368], "direcao": "", "observacao": ""},
        {"nome": "olho esquerdo", "animacoes": ["piscar"], "caixa": [484, 244, 506, 266],
         "pivo": [495, 255], "direcao": "", "observacao": ""},
        {"nome": "olho direito", "animacoes": ["piscar"], "caixa": [537, 244, 559, 266],
         "pivo": [548, 255], "direcao": "", "observacao": ""},
    ], "nao_encontrados": [], "camera": "zoom_in"}


def escolher_resposta(pedido: dict) -> dict:
    sistema = pedido["system"][0]["text"]
    if "roteirista-chefe" in sistema:
        return resposta_titulos(pedido)
    if "Você escreve roteiros" in sistema:
        return resposta_roteiro(pedido)
    if "storyboarder" in sistema:
        return resposta_cenas(pedido)
    if "Você localiza partes" in sistema:
        return resposta_deteccao(pedido)
    raise ValueError("pedido desconhecido")


class ServidorFalso:
    def __init__(self):
        self.pedidos: list[dict] = []
        servidor = self

        class Tratador(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                tamanho = int(self.headers.get("content-length", 0))
                pedido = json.loads(self.rfile.read(tamanho))
                servidor.pedidos.append(pedido)
                corpo = _sse(json.dumps(escolher_resposta(pedido), ensure_ascii=False))
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("content-length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Tratador)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> "ServidorFalso":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
