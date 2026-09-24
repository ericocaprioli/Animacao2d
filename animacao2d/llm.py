"""Acesso à IA: Claude pela API ou modo manual (copiar/colar no claude.ai).

Todas as chamadas pedem JSON num formato fixo (structured outputs), então o
resto do programa nunca precisa "adivinhar" o que a IA respondeu.
"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any

from animacao2d import config
from animacao2d.util import Progresso, extrair_json, perguntar, salvar_texto

BETA_FALLBACK = "server-side-fallback-2026-07-01"


class ErroIA(RuntimeError):
    pass


# ---------------------------------------------------------------- validação

def validar_schema(dados: Any, schema: dict, caminho: str = "resposta") -> list[str]:
    """Validação leve do subconjunto de JSON Schema usado aqui."""
    erros: list[str] = []
    tipo = schema.get("type")
    tipos = {
        "object": dict, "array": list, "string": str, "boolean": bool,
        "integer": int, "number": (int, float),
    }
    if tipo in tipos:
        esperado = tipos[tipo]
        if not isinstance(dados, esperado) or (tipo in ("integer", "number") and isinstance(dados, bool)):
            return [f"{caminho}: esperava {tipo}, veio {type(dados).__name__}"]
    if "enum" in schema and dados not in schema["enum"]:
        erros.append(f"{caminho}: valor '{dados}' fora das opções {schema['enum']}")
    if tipo == "object":
        for chave in schema.get("required", []):
            if chave not in dados:
                erros.append(f"{caminho}: falta o campo '{chave}'")
        for chave, sub in schema.get("properties", {}).items():
            if chave in dados:
                erros.extend(validar_schema(dados[chave], sub, f"{caminho}.{chave}"))
    elif tipo == "array" and "items" in schema:
        for i, item in enumerate(dados):
            erros.extend(validar_schema(item, schema["items"], f"{caminho}[{i}]"))
    return erros


# ---------------------------------------------------------------- conteúdo

def bloco_texto(texto: str, cache: bool = False) -> dict:
    bloco: dict[str, Any] = {"type": "text", "text": texto}
    if cache:
        bloco["cache_control"] = {"type": "ephemeral"}
    return bloco


def bloco_imagem(rgb, qualidade: int = 92) -> dict:
    """Imagem (array RGB) como bloco base64 JPEG."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.fromarray(rgb).save(buffer, format="JPEG", quality=qualidade)
    dados = base64.standard_b64encode(buffer.getvalue()).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": dados}}


def _texto_do_conteudo(conteudo: list[dict] | str) -> str:
    if isinstance(conteudo, str):
        return conteudo
    partes = []
    for bloco in conteudo:
        if bloco.get("type") == "text":
            partes.append(bloco["text"])
        elif bloco.get("type") == "image":
            partes.append("[IMAGEM: anexe a imagem da cena junto com este pedido]")
    return "\n\n".join(partes)


# ---------------------------------------------------------------- clientes

class ClienteIA:
    nome = "base"
    aceita_imagem = True

    def gerar_json(self, *, tarefa: str, sistema: str, conteudo: list[dict] | str, schema: dict,
                   esforco: str = "high", max_tokens: int = 64000, visao: bool = False,
                   mensagem: str = "Pensando") -> dict:
        raise NotImplementedError


class ClaudeIA(ClienteIA):
    """Claude via API oficial (SDK `anthropic`)."""

    nome = "claude"

    def __init__(self, modelo: str | None = None, modelo_visao: str | None = None, cliente: Any = None):
        try:
            import anthropic
        except ImportError as erro:  # pragma: no cover - dependência obrigatória
            raise ErroIA("Pacote 'anthropic' não instalado. Rode: pip install -r requirements.txt") from erro
        self._anthropic = anthropic
        self.modelo = modelo or config.modelo_texto()
        self.modelo_visao = modelo_visao or config.modelo_visao()
        try:
            self.cliente = cliente or anthropic.Anthropic(max_retries=4)
        except anthropic.AnthropicError as erro:
            raise ErroIA(_mensagem_sem_chave()) from erro

    def gerar_json(self, *, tarefa: str, sistema: str, conteudo: list[dict] | str, schema: dict,
                   esforco: str = "high", max_tokens: int = 64000, visao: bool = False,
                   mensagem: str = "Pensando") -> dict:
        anthropic = self._anthropic
        modelo = self.modelo_visao if visao else self.modelo
        blocos = [bloco_texto(conteudo)] if isinstance(conteudo, str) else conteudo
        caracteres = 0
        try:
            with Progresso(mensagem) as progresso:
                with self.cliente.beta.messages.stream(
                    model=modelo,
                    max_tokens=max_tokens,
                    system=[bloco_texto(sistema, cache=True)],
                    messages=[{"role": "user", "content": blocos}],
                    thinking={"type": "adaptive"},
                    output_config={"effort": esforco, "format": {"type": "json_schema", "schema": schema}},
                    betas=[BETA_FALLBACK],
                    fallbacks="default",
                ) as stream:
                    for evento in stream:
                        if getattr(evento, "type", "") == "text":
                            caracteres += len(evento.text)
                            progresso.detalhe = f"({caracteres} caracteres)"
                    final = stream.get_final_message()
        except anthropic.AuthenticationError as erro:
            raise ErroIA("A chave da API foi recusada (ANTHROPIC_API_KEY inválida).") from erro
        except anthropic.PermissionDeniedError as erro:
            raise ErroIA(f"Sem permissão para usar o modelo {modelo}: {erro.message}") from erro
        except anthropic.NotFoundError as erro:
            raise ErroIA(f"Modelo '{modelo}' não encontrado. Ajuste ANIMACAO2D_MODELO no .env.") from erro
        except anthropic.RateLimitError as erro:
            raise ErroIA("Limite de uso da API atingido. Espere um pouco e rode de novo.") from erro
        except anthropic.BadRequestError as erro:
            raise ErroIA(f"A API recusou o pedido: {erro.message}") from erro
        except anthropic.APIStatusError as erro:
            raise ErroIA(f"Erro da API ({erro.status_code}): {erro.message}") from erro
        except anthropic.APIConnectionError as erro:
            raise ErroIA("Sem conexão com a API da Anthropic. Verifique a internet.") from erro
        except anthropic.AnthropicError as erro:
            raise ErroIA(f"{_mensagem_sem_chave()}\nDetalhe: {erro}") from erro
        except TypeError as erro:
            if "authentication" in str(erro).lower():  # SDK sem nenhuma credencial configurada
                raise ErroIA(_mensagem_sem_chave()) from erro
            raise

        if final.stop_reason == "refusal":
            raise ErroIA("A IA se recusou a responder este pedido. Reformule o tema/pedido e tente de novo.")
        if final.stop_reason == "max_tokens":
            raise ErroIA("A resposta da IA foi cortada por ser longa demais. Tente de novo (ou divida o pedido).")
        texto = "".join(b.text for b in final.content if getattr(b, "type", "") == "text")
        try:
            dados = json.loads(texto)
        except json.JSONDecodeError:
            dados = extrair_json(texto)
        erros = validar_schema(dados, schema)
        if erros:
            raise ErroIA("A IA devolveu um JSON inesperado: " + "; ".join(erros[:5]))
        return dados


class ManualIA(ClienteIA):
    """Sem API: grava o pedido num arquivo para colar no claude.ai e lê a resposta."""

    nome = "manual"
    aceita_imagem = False

    def __init__(self, pasta: str | Path):
        self.pasta = Path(pasta) / "_manual"

    def gerar_json(self, *, tarefa: str, sistema: str, conteudo: list[dict] | str, schema: dict,
                   esforco: str = "high", max_tokens: int = 64000, visao: bool = False,
                   mensagem: str = "Pensando") -> dict:
        if visao:
            raise ErroIA("O modo manual não localiza partes na imagem. Use o editor visual (animacao2d editor).")
        pedido = self.pasta / f"{tarefa}_pedido.md"
        resposta = self.pasta / f"{tarefa}_resposta.json"
        texto = (
            f"# Pedido: {tarefa}\n\n"
            "Cole TODO este texto numa conversa nova do Claude (claude.ai).\n\n"
            "## Instruções\n\n"
            f"{sistema}\n\n"
            "## Tarefa\n\n"
            f"{_texto_do_conteudo(conteudo)}\n\n"
            "## Formato da resposta\n\n"
            "Responda SOMENTE com um JSON válido (sem comentários) que siga este JSON Schema:\n\n"
            f"```json\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n```\n"
        )
        salvar_texto(pedido, texto)
        print(f"\n[modo manual] {mensagem}")
        print(f"  1. Abra {pedido} e cole o conteúdo no claude.ai")
        print(f"  2. Salve a resposta (o JSON) em {resposta}")
        while True:
            comando = perguntar("  3. Pressione Enter quando salvar (ou 'c' para cancelar): ").lower()
            if comando == "c":
                raise ErroIA("Cancelado.")
            if not resposta.is_file():
                print(f"  Ainda não encontrei {resposta}.")
                continue
            try:
                dados = extrair_json(resposta.read_text(encoding="utf-8"))
            except ValueError as erro:
                print(f"  O arquivo não tem um JSON válido: {erro}")
                continue
            erros = validar_schema(dados, schema)
            if erros:
                print("  O JSON não está no formato esperado:\n   - " + "\n   - ".join(erros[:8]))
                continue
            return dados


def _mensagem_sem_chave() -> str:
    return (
        "Não consegui acessar a API da Anthropic. Crie um arquivo .env com ANTHROPIC_API_KEY=... "
        "(veja .env.exemplo) ou rode com --manual para copiar e colar os pedidos no claude.ai."
    )


def criar_cliente(manual: bool = False, pasta: str | Path = ".") -> ClienteIA:
    return ManualIA(pasta) if manual else ClaudeIA()
