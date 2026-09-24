"""Acesso à IA: Claude pela API ou modo manual (copiar/colar no claude.ai).

Todas as chamadas pedem JSON num formato fixo (structured outputs), então o
resto do programa nunca precisa "adivinhar" o que a IA respondeu.
"""

from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from animacao2d import config
from animacao2d.util import Progresso, extrair_json, salvar_texto

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
                   mensagem: str = "Pensando", anexos: list[Path] | None = None) -> dict:
        """Pede um JSON no formato `schema`. `anexos`: arquivos que o modo manual pede para anexar."""
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
                   mensagem: str = "Pensando", anexos: list[Path] | None = None) -> dict:
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
    """Grátis, sem API: você cola o pedido no claude.ai (ou em outro chat) e cola a resposta de volta.

    - o pedido é gravado em _manual/<etapa>_pedido.txt e aberto automaticamente;
    - para localizar partes numa imagem, o programa indica qual imagem anexar na conversa;
    - a resposta pode ser colada direto no terminal (ou salva em _manual/<etapa>_resposta.json);
    - pedidos seguidos com o mesmo contexto (as seções das cenas) viram pedidos curtos
      para colar na MESMA conversa, sem repetir o roteiro inteiro.
    """

    nome = "manual"
    aceita_imagem = False  # a imagem não vai no texto: você anexa o arquivo na conversa

    def __init__(self, pasta: str | Path, abrir_arquivo: bool | None = None):
        self.pasta = Path(pasta) / "_manual"
        if abrir_arquivo is None:
            abrir_arquivo = not os.environ.get("ANIMACAO2D_NAO_ABRIR")
        self.abrir_arquivo = abrir_arquivo
        self._contexto_anterior: tuple | None = None
        self._tarefa_anterior = ""

    def gerar_json(self, *, tarefa: str, sistema: str, conteudo: list[dict] | str, schema: dict,
                   esforco: str = "high", max_tokens: int = 64000, visao: bool = False,
                   mensagem: str = "Pensando", anexos: list[Path] | None = None) -> dict:
        blocos = [bloco_texto(conteudo)] if isinstance(conteudo, str) else conteudo
        fixos = tuple(b["text"] for b in blocos if b.get("type") == "text" and b.get("cache_control"))
        variaveis = [b for b in blocos if not b.get("cache_control")]
        contexto = (sistema, fixos, json.dumps(schema, sort_keys=True))
        completo = _pedido_completo(sistema, blocos, schema)
        pedido = self.pasta / f"{tarefa}_pedido.txt"
        resposta = self.pasta / f"{tarefa}_resposta.json"
        continuacao = bool(fixos) and contexto == self._contexto_anterior
        if continuacao:
            salvar_texto(self.pasta / f"{tarefa}_pedido_completo.txt", completo)
            texto = (f"(Cole na MESMA conversa do pedido anterior: {self._tarefa_anterior})\n\n"
                     f"{_texto_do_conteudo(variaveis)}\n\n"
                     "Responda SOMENTE com o JSON, no mesmo formato da sua resposta anterior.\n")
        else:
            texto = completo
        salvar_texto(pedido, texto)
        self._contexto_anterior, self._tarefa_anterior = contexto, tarefa

        print(f"\n[modo manual] {mensagem}")
        onde = "na MESMA conversa do pedido anterior" if continuacao else "numa conversa NOVA"
        passo = 1
        if anexos:
            nomes = ", ".join(str(a) for a in anexos)
            print(f"  {passo}. Numa conversa NOVA do claude.ai, anexe a imagem: {nomes}")
            print("     (arraste o arquivo para a caixa de mensagem ou use o clipe de anexar)")
            onde = "na mesma mensagem"
            passo += 1
        print(f"  {passo}. Copie todo o texto de {pedido} (Ctrl+A, Ctrl+C) e cole {onde}. Envie.")
        print(f"  {passo + 1}. Copie a resposta (o bloco JSON) e cole aqui embaixo. Depois aperte Enter numa linha vazia.")
        print(f"     (ou salve a resposta em {resposta} e aperte Enter; 'c' cancela)")
        if self.abrir_arquivo:
            for anexo in anexos or []:
                _mostrar_no_explorador(anexo)
            _abrir_no_sistema(pedido)
        return self._ler_resposta(resposta, schema)

    def _ler_resposta(self, arquivo: Path, schema: dict) -> dict:
        while True:
            texto = _ler_colado()
            if not texto.strip():
                if not arquivo.is_file():
                    print(f"  Nada colado e não encontrei {arquivo}. Cole a resposta ou salve o arquivo.")
                    continue
                texto = arquivo.read_text(encoding="utf-8")
            try:
                dados = extrair_json(texto)
            except ValueError:
                print("  Não achei um JSON completo nisso. Copie a resposta inteira (o bloco de código) e cole de novo.")
                continue
            erros = validar_schema(dados, schema)
            if erros:
                print("  O JSON não está no formato esperado (peça ao Claude para corrigir e cole de novo):\n   - "
                      + "\n   - ".join(erros[:8]))
                continue
            salvar_texto(arquivo, json.dumps(dados, ensure_ascii=False, indent=2) + "\n")
            return dados


def _pedido_completo(sistema: str, blocos: list[dict], schema: dict) -> str:
    return (
        "=== INSTRUÇÕES ===\n\n"
        f"{sistema}\n\n"
        "=== TAREFA ===\n\n"
        f"{_texto_do_conteudo(blocos)}\n\n"
        "=== FORMATO DA RESPOSTA ===\n\n"
        "Responda SOMENTE com um JSON válido (sem comentários, sem texto antes ou depois) que siga este "
        "JSON Schema:\n\n"
        f"{json.dumps(schema, ensure_ascii=False, indent=2)}\n"
    )


def _ler_colado() -> str:
    """Lê várias linhas coladas no terminal até uma linha vazia depois de um JSON completo."""
    linhas: list[str] = []
    while True:
        try:
            linha = input("  > " if not linhas else "")
        except EOFError:
            break
        comando = linha.strip().lower()
        if comando in ("c", "cancelar"):
            raise ErroIA("Cancelado.")
        if comando == "fim":
            break
        if not comando:
            if not linhas:
                break  # Enter sem colar nada: tenta o arquivo de resposta
            try:
                extrair_json("\n".join(linhas))
                break
            except ValueError:
                continue  # linha vazia no meio (texto antes do JSON): continua lendo
        linhas.append(linha)
    return "\n".join(linhas)


def _abrir_no_sistema(caminho: Path) -> None:
    """Abre o arquivo no editor de texto padrão (melhor esforço)."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(caminho))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(caminho)])
        else:
            subprocess.Popen(["xdg-open", str(caminho)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, ValueError):
        pass


def _mostrar_no_explorador(caminho: Path) -> None:
    """Abre a pasta com o arquivo selecionado, para arrastar para o claude.ai (melhor esforço)."""
    try:
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", str(Path(caminho).resolve())])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(caminho)])
        else:
            subprocess.Popen(["xdg-open", str(Path(caminho).resolve().parent)], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
    except (OSError, ValueError):
        pass


def _mensagem_sem_chave() -> str:
    return (
        "Não consegui acessar a API da Anthropic. Para usar tudo de graça (copiando e colando no claude.ai), "
        "ponha ANIMACAO2D_IA=manual no .env ou rode com --manual. Para usar a API, ponha "
        "ANTHROPIC_API_KEY=... no .env (veja .env.exemplo)."
    )


def modo_ia() -> str:
    """"manual" (grátis: copiar/colar no claude.ai) ou "api".

    ANIMACAO2D_IA=manual|api no .env decide. Sem essa linha: API se houver chave, senão manual.
    """
    valor = os.environ.get("ANIMACAO2D_IA", "").strip().lower()
    if valor in ("manual", "gratis", "grátis"):
        return "manual"
    if valor == "api":
        return "api"
    if os.environ.get("ANIMACAO2D_TEXTO", "").strip().lower() == "manual":
        return "manual"
    tem_chave = any(os.environ.get(v, "").strip() for v in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"))
    return "api" if tem_chave else "manual"


def criar_cliente(manual: bool = False, pasta: str | Path = ".") -> ClienteIA:
    return ManualIA(pasta) if manual else ClaudeIA()
