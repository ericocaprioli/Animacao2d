"""Servidor falso da API da Anthropic (SSE) para testar o cliente sem rede."""

from __future__ import annotations

import json

import anthropic
import httpx2


def _sse(texto: str, stop_reason: str = "end_turn", modelo: str = "claude-opus-5") -> bytes:
    eventos = [
        ("message_start", {"type": "message_start", "message": {
            "id": "msg_teste", "type": "message", "role": "assistant", "model": modelo, "content": [],
            "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 1}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "text", "text": ""}}),
    ]
    metade = len(texto) // 2
    for pedaco in (texto[:metade], texto[metade:]):
        eventos.append(("content_block_delta", {"type": "content_block_delta", "index": 0,
                                                "delta": {"type": "text_delta", "text": pedaco}}))
    eventos += [
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                           "usage": {"output_tokens": 42}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    return "".join(f"event: {nome}\ndata: {json.dumps(dados)}\n\n" for nome, dados in eventos).encode()


class ApiFalsa:
    """Responde cada pedido com o próximo item de `respostas` (dict/str)."""

    def __init__(self, respostas, stop_reason: str = "end_turn"):
        self.respostas = list(respostas)
        self.stop_reason = stop_reason
        self.pedidos: list[dict] = []
        self.cabecalhos: list[dict] = []

    def _tratar(self, request: httpx2.Request) -> httpx2.Response:
        self.pedidos.append(json.loads(request.content))
        self.cabecalhos.append(dict(request.headers))
        resposta = self.respostas.pop(0)
        texto = resposta if isinstance(resposta, str) else json.dumps(resposta, ensure_ascii=False)
        return httpx2.Response(200, headers={"content-type": "text/event-stream"},
                               content=_sse(texto, self.stop_reason))

    def cliente(self) -> anthropic.Anthropic:
        transporte = httpx2.MockTransport(self._tratar)
        return anthropic.Anthropic(api_key="teste", base_url="http://api.falsa",
                                   http_client=anthropic.DefaultHttpxClient(transport=transporte), max_retries=0)
