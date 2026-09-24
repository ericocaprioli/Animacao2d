"""Títulos e roteiro: geração com IA e conversão roteiro.md <-> estrutura."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from animacao2d import config
from animacao2d.llm import ClienteIA, bloco_texto
from animacao2d.prompts import SCHEMA_ROTEIRO, SCHEMA_TITULOS, SISTEMA_ROTEIRO, SISTEMA_TITULOS
from animacao2d.util import contar_palavras, formatar_tempo


@dataclass
class Personagem:
    tag: str
    nome: str
    papel: str
    descricao_visual: str


@dataclass
class Secao:
    titulo: str
    tipo: str  # gancho | capitulo | conclusao
    texto: str


@dataclass
class Roteiro:
    titulo: str
    descricao: str = ""
    personagens: list[Personagem] = field(default_factory=list)
    secoes: list[Secao] = field(default_factory=list)

    @property
    def palavras(self) -> int:
        """Palavras faladas (sem as tags "DEV:" das falas)."""
        return sum(contar_palavras(re.sub(r"(?m)^\s*[A-Z][A-Z0-9_]{1,24}:\s*", "", s.texto)) for s in self.secoes)

    def duracao_estimada(self, palavras_por_minuto: float = config.PALAVRAS_POR_MINUTO) -> float:
        return self.palavras / palavras_por_minuto * 60.0

    def resumo(self, palavras_por_minuto: float = config.PALAVRAS_POR_MINUTO) -> str:
        return (f"{self.palavras} palavras, ~{formatar_tempo(self.duracao_estimada(palavras_por_minuto))} de "
                f"narração, {len(self.secoes)} seções, {len(self.personagens)} personagens")

    @classmethod
    def de_dict(cls, dados: dict) -> "Roteiro":
        tags_vistas = set()
        personagens = []
        for p in dados.get("personagens", []):
            tag = normalizar_tag(p.get("tag", ""))
            if tag and tag not in tags_vistas:
                tags_vistas.add(tag)
                personagens.append(Personagem(tag, p.get("nome", tag), p.get("papel", ""),
                                              p.get("descricao_visual", "")))
        secoes = [Secao(s.get("titulo", ""), s.get("tipo", "capitulo"), s.get("texto", "").strip())
                  for s in dados.get("secoes", []) if s.get("texto", "").strip()]
        return cls(dados.get("titulo", ""), dados.get("descricao", ""), personagens, secoes)

    def para_dict(self) -> dict:
        return {
            "titulo": self.titulo,
            "descricao": self.descricao,
            "personagens": [p.__dict__ for p in self.personagens],
            "secoes": [s.__dict__ for s in self.secoes],
        }

    # ------------------------------------------------------------ markdown

    def para_markdown(self) -> str:
        linhas = [f"# {self.titulo}", ""]
        if self.descricao:
            linhas += [f"> {self.descricao}", ""]
        linhas += ["<!-- Pode editar à vontade: títulos das seções (## [tipo] Título), falas no formato "
                   "\"TAG: fala\" e as descrições dos personagens. Depois rode: animacao2d cenas -->", ""]
        if self.personagens:
            linhas += ["## Personagens", ""]
            for p in self.personagens:
                linhas.append(f"- **{p.tag}** ({p.nome}): {p.papel} — `{p.descricao_visual}`")
            linhas.append("")
        for s in self.secoes:
            linhas += [f"## [{s.tipo}] {s.titulo}", "", s.texto.strip(), ""]
        return "\n".join(linhas).rstrip() + "\n"

    @classmethod
    def de_markdown(cls, texto: str) -> "Roteiro":
        titulo, descricao = "", ""
        personagens: list[Personagem] = []
        secoes: list[Secao] = []
        atual: Secao | None = None
        em_personagens = False
        corpo: list[str] = []

        def fechar() -> None:
            if atual is not None:
                atual.texto = "\n".join(corpo).strip()
                if atual.texto:
                    secoes.append(atual)

        texto = re.sub(r"<!--.*?-->", "", texto, flags=re.S)
        for linha in texto.splitlines():
            if linha.startswith("# ") and not titulo:
                titulo = linha[2:].strip()
                continue
            if linha.startswith("## "):
                fechar()
                atual, corpo = None, []
                cabecalho = linha[3:].strip()
                em_personagens = cabecalho.lower().startswith("personagens")
                if not em_personagens:
                    achado = re.match(r"\[(\w+)\]\s*(.*)", cabecalho)
                    tipo, nome = (achado.group(1).lower(), achado.group(2)) if achado else ("capitulo", cabecalho)
                    if tipo not in ("gancho", "capitulo", "conclusao"):
                        tipo = "capitulo"
                    atual = Secao(nome.strip(), tipo, "")
                continue
            if em_personagens:
                achado = re.match(r"-\s*\*\*(.+?)\*\*\s*(?:\((.*?)\))?\s*:?\s*(.*?)\s*(?:—|-)\s*`(.+?)`", linha)
                if achado:
                    tag = normalizar_tag(achado.group(1))
                    personagens.append(Personagem(tag, achado.group(2) or tag, achado.group(3).strip(),
                                                  achado.group(4).strip()))
                continue
            if atual is None:
                if linha.startswith("> ") and not descricao:
                    descricao = linha[2:].strip()
                continue
            corpo.append(linha)
        fechar()
        return cls(titulo, descricao, personagens, secoes)


def normalizar_tag(tag: str) -> str:
    return re.sub(r"[^A-Z0-9_]", "", tag.upper().replace(" ", "_"))


def palavras_alvo(minutos: float, palavras_por_minuto: float = config.PALAVRAS_POR_MINUTO) -> int:
    return int(round(minutos * palavras_por_minuto))


# ---------------------------------------------------------------- IA

def sugerir_titulos(ia: ClienteIA, tema: str, quantidade: int = 8) -> list[dict]:
    texto = (f"Tema: {tema}\nQuantidade de títulos: {quantidade}\n"
             "Público: brasileiros curiosos, sem formação técnica. Idioma: português do Brasil.")
    dados = ia.gerar_json(tarefa="titulos", sistema=SISTEMA_TITULOS, conteudo=[bloco_texto(texto)],
                          schema=SCHEMA_TITULOS, esforco="medium", max_tokens=16000,
                          mensagem="Pensando em títulos")
    return [t for t in dados["titulos"] if t.get("titulo", "").strip()][:quantidade]


def escrever_roteiro(ia: ClienteIA, titulo: str, tema: str, minutos: float = config.MINUTOS_PADRAO,
                     palavras_por_minuto: float = config.PALAVRAS_POR_MINUTO, pedido_extra: str = "",
                     anterior: Roteiro | None = None, ajustar_tamanho: bool = True) -> Roteiro:
    """Escreve (ou reescreve, se `anterior`) o roteiro. Refaz uma vez se ficar curto/longo demais."""
    alvo = palavras_alvo(minutos, palavras_por_minuto)
    capitulos = max(3, min(9, round(minutos / 2.5)))
    texto = (f"Título aprovado: {titulo}\nTema: {tema}\n"
             f"Duração alvo: {minutos:g} minutos de narração = cerca de {alvo} palavras no total.\n"
             f"Capítulos: {capitulos} (além do gancho e da conclusão).")
    if anterior is not None:
        texto += ("\n\nRoteiro atual (reescreva a partir dele, mantendo o que está bom):\n\n"
                  + anterior.para_markdown())
    if pedido_extra:
        texto += f"\n\nPedido do autor para esta versão: {pedido_extra}"
    dados = ia.gerar_json(tarefa="roteiro", sistema=SISTEMA_ROTEIRO, conteudo=[bloco_texto(texto)],
                          schema=SCHEMA_ROTEIRO, esforco="high", max_tokens=64000,
                          mensagem="Escrevendo o roteiro")
    roteiro = Roteiro.de_dict(dados)
    roteiro.titulo = roteiro.titulo or titulo
    if ajustar_tamanho and not (0.85 * alvo <= roteiro.palavras <= 1.15 * alvo):
        acao = "expandir" if roteiro.palavras < alvo else "enxugar"
        pedido = (f"A versão anterior ficou com {roteiro.palavras} palavras, mas o alvo é {alvo}. "
                  f"Reescreva para {acao} até ~{alvo} palavras, mantendo estrutura, personagens e piadas.")
        if pedido_extra:
            pedido += f" Mantenha também este pedido do autor: {pedido_extra}"
        return escrever_roteiro(ia, titulo, tema, minutos, palavras_por_minuto, pedido, roteiro,
                                ajustar_tamanho=False)
    return roteiro
