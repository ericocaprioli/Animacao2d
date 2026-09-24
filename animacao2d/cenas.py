"""Divide o roteiro em cenas: prompts de imagem, animações, câmera e tempos.

O texto é cortado em pedaços pequenos (frases/orações) pelo programa, e a IA só
decide como AGRUPAR pedaços consecutivos em cenas. Assim nenhuma frase da
narração se perde e os tempos de cada cena são calculados com precisão.
"""

from __future__ import annotations

import csv
import io
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from animacao2d import config
from animacao2d.animacao.catalogo import ANIMACOES, resolver_camera
from animacao2d.llm import ClienteIA, bloco_texto
from animacao2d.prompts import SCHEMA_CENAS, sistema_cenas
from animacao2d.roteiro import Roteiro
from animacao2d.util import contar_palavras, formatar_srt, formatar_tempo, nome_cena, sem_acentos

_RE_FALA = re.compile(r"^([A-Z][A-Z0-9_]{1,24}):\s*(.+)$", re.S)


@dataclass
class Trecho:
    texto: str
    falante: str = ""  # TAG do personagem ou "" (narrador)

    @property
    def palavras(self) -> int:
        return contar_palavras(self.texto)

    def duracao(self, palavras_por_minuto: float) -> float:
        return max(0.8, self.palavras / palavras_por_minuto * 60.0)


_PALAVRAS_DE_CORTE = {"que", "e", "mas", "porque", "quando", "onde", "enquanto", "para", "pra", "com", "sem", "se",
                      "como", "entao", "ou", "ate", "pois", "depois", "antes", "so", "mesmo", "tipo"}


def _dividir_por_palavras(texto: str, maximo: int) -> list[str]:
    """Corta antes de uma conjunção/preposição perto do meio (nunca no meio de 'fim de semana')."""
    palavras = texto.split()
    if len(palavras) <= maximo * 1.4:
        return [texto]
    meio = len(palavras) / 2
    candidatos = [i for i in range(4, len(palavras) - 3)
                  if sem_acentos(palavras[i].lower().strip(",.;:!?")) in _PALAVRAS_DE_CORTE]
    corte = min(candidatos, key=lambda i: abs(i - meio)) if candidatos else int(round(meio))
    return (_dividir_por_palavras(" ".join(palavras[:corte]), maximo)
            + _dividir_por_palavras(" ".join(palavras[corte:]), maximo))


def _quebrar_longa(frase: str, maximo: int) -> list[str]:
    if contar_palavras(frase) <= maximo:
        return [frase]
    # primeiro tenta vírgulas, ponto e vírgula, dois pontos e travessões
    oracoes = [o.strip() for o in re.split(r"(?<=[,;:])\s+|\s+(?=[—–]\s)", frase) if o.strip()]
    juntas: list[str] = []
    for oracao in oracoes:
        anterior = contar_palavras(juntas[-1]) if juntas else 0
        atual = contar_palavras(oracao)
        if juntas and (anterior < 3 or ((anterior < 4 or atual < 4) and anterior + atual <= maximo * 1.4)):
            juntas[-1] = f"{juntas[-1]} {oracao}"
        else:
            juntas.append(oracao)
    resultado: list[str] = []
    for pedaco in juntas:
        resultado += _dividir_por_palavras(pedaco, maximo)
    return resultado


def dividir_em_trechos(texto: str, maximo_palavras: int = 12) -> list[Trecho]:
    """Parágrafos -> frases -> orações, cada trecho com no máximo ~`maximo_palavras` palavras."""
    trechos: list[Trecho] = []
    for paragrafo in re.split(r"\n\s*\n|\n", texto):
        paragrafo = " ".join(paragrafo.split())
        if not paragrafo:
            continue
        falante = ""
        achado = _RE_FALA.match(paragrafo)
        if achado:
            falante, paragrafo = achado.group(1), achado.group(2).strip()
        frases = [f.strip() for f in re.split(r"(?<=[.!?…])\s+(?=[\"“'(\-—A-ZÀ-Ý0-9¿¡])", paragrafo) if f.strip()]
        for frase in frases:
            for pedaco in _quebrar_longa(frase, maximo_palavras):
                trechos.append(Trecho(pedaco, falante))
    return trechos


def texto_da_narracao(trechos: list[Trecho]) -> str:
    """Junta trechos repetindo a TAG só quando o falante muda."""
    partes: list[str] = []
    falante_atual = None
    for trecho in trechos:
        if trecho.falante != falante_atual:
            prefixo = f"{trecho.falante}: " if trecho.falante else ""
            partes.append(prefixo + trecho.texto)
            falante_atual = trecho.falante
        else:
            partes[-1] += " " + trecho.texto
    return "\n".join(partes)


# ---------------------------------------------------------------- reparo

def reparar_grupos(cenas: list[dict], total: int) -> list[dict]:
    """Garante que as cenas cobrem os trechos 1..total, em ordem, sem buracos nem sobreposição."""
    validas = []
    for cena in sorted(cenas, key=lambda c: (int(c.get("inicio", 0)), int(c.get("fim", 0)))):
        inicio, fim = int(cena.get("inicio", 0)), int(cena.get("fim", 0))
        inicio, fim = max(1, inicio), min(total, fim)
        if fim < inicio:
            continue
        validas.append({**cena, "inicio": inicio, "fim": fim})
    if not validas:
        return [{"inicio": 1, "fim": total, "plano": "geral", "descricao": "", "expressao": "", "prompt": "",
                 "animacoes": [], "camera": "zoom_in", "texto_na_tela": ""}]
    reparadas: list[dict] = []
    proximo = 1
    for cena in validas:
        if cena["fim"] < proximo:
            continue  # totalmente coberta pela anterior
        if cena["inicio"] > proximo:
            if reparadas:
                reparadas[-1]["fim"] = cena["inicio"] - 1  # buraco: estende a anterior
            else:
                cena["inicio"] = 1
        cena["inicio"] = max(cena["inicio"], proximo) if reparadas else cena["inicio"]
        reparadas.append(cena)
        proximo = cena["fim"] + 1
    reparadas[-1]["fim"] = total
    return reparadas


# ---------------------------------------------------------------- prompts finais

def montar_prompt(base: str, personagens: dict[str, str], estilo: str) -> str:
    def trocar(achado: re.Match) -> str:
        tag = achado.group(1).upper()
        return personagens.get(tag, achado.group(1).title())

    # "the [DEV]" / "a [DEV]" -> só a descrição (que já começa com "a"/"an")
    base = re.sub(r"\b(?:[Tt]he|[Aa]n?)\s+(\[[A-Za-z0-9_ ]{1,30}\])", r"\1", base.strip())
    conteudo = re.sub(r"\[([A-Za-z0-9_ ]{1,30})\]", trocar, base).rstrip(" .")
    return f"{conteudo}. {estilo}" if estilo else conteudo


# ---------------------------------------------------------------- geração

def _texto_personagens(roteiro: Roteiro) -> str:
    if not roteiro.personagens:
        return "(sem personagens recorrentes)"
    return "\n".join(f"- [{p.tag}] {p.nome} ({p.papel}): {p.descricao_visual}" for p in roteiro.personagens)


def gerar_cenas(ia: ClienteIA, roteiro: Roteiro, ritmo: str = config.RITMO_PADRAO,
                palavras_por_minuto: float = config.PALAVRAS_POR_MINUTO, estilo: str = "",
                paralelo: int = 1) -> list[dict]:
    """Gera o plano de cenas do roteiro inteiro (uma chamada à IA por seção)."""
    r = config.RITMOS[ritmo]
    maximo_palavras = int(max(6, min(16, round(r.media_s * palavras_por_minuto / 60.0 * 0.95))))
    sistema = sistema_cenas(r.media_s, r.minimo_s, r.maximo_s)
    # bloco comum a todas as seções (vai para o cache da API)
    contexto = (f"Título do vídeo: {roteiro.titulo}\n\nPersonagens recorrentes:\n{_texto_personagens(roteiro)}\n\n"
                f"Roteiro completo (só para contexto):\n\n{roteiro.para_markdown()}")
    trechos_por_secao = [dividir_em_trechos(s.texto, maximo_palavras) for s in roteiro.secoes]

    def gerar_secao(indice: int) -> list[dict]:
        secao = roteiro.secoes[indice]
        trechos = trechos_por_secao[indice]
        if not trechos:
            return []
        linhas = []
        for n, trecho in enumerate(trechos, 1):
            fala = f"[{trecho.falante} fala] " if trecho.falante else ""
            linhas.append(f"T{n} ({trecho.duracao(palavras_por_minuto):.1f}s): {fala}{trecho.texto}")
        pedido = (f"Seção {indice + 1} de {len(roteiro.secoes)} — tipo: {secao.tipo} — título: {secao.titulo}\n"
                  f"{'Comece com uma cena cartela para este capítulo.' if secao.tipo == 'capitulo' else ''}\n\n"
                  f"Pedaços ({len(trechos)} no total; use inicio/fim com os números, de 1 a {len(trechos)}):\n"
                  + "\n".join(linhas))
        dados = ia.gerar_json(
            tarefa=f"cenas_secao{indice + 1:02d}", sistema=sistema,
            conteudo=[bloco_texto(contexto, cache=True), bloco_texto(pedido)],
            schema=SCHEMA_CENAS, esforco="high", max_tokens=64000,
            mensagem=f"Cenas da seção {indice + 1}/{len(roteiro.secoes)} ({secao.titulo})",
        )
        grupos = reparar_grupos(dados["cenas"], len(trechos))
        cenas = []
        for grupo in grupos:
            pedacos = trechos[grupo["inicio"] - 1:grupo["fim"]]
            animacoes = [{"elemento": a["elemento"].strip(), "animacao": a["animacao"]}
                         for a in grupo.get("animacoes", []) if a.get("animacao") in ANIMACOES and a.get("elemento")]
            try:
                camera = resolver_camera(grupo.get("camera"))
            except ValueError:
                camera = "zoom_in"
            cenas.append({
                "secao": indice + 1,
                "secao_titulo": secao.titulo,
                "narracao": texto_da_narracao(pedacos),
                "falantes": sorted({t.falante for t in pedacos if t.falante}),
                "palavras": sum(t.palavras for t in pedacos),
                "duracao": round(sum(t.duracao(palavras_por_minuto) for t in pedacos), 2),
                "plano": grupo.get("plano", "geral"),
                "descricao": grupo.get("descricao", ""),
                "expressao": grupo.get("expressao", ""),
                "prompt_base": grupo.get("prompt", ""),
                "animacoes": animacoes[:3],
                "camera": camera,
                "texto_na_tela": grupo.get("texto_na_tela", ""),
            })
        return cenas

    indices = list(range(len(roteiro.secoes)))
    if paralelo > 1:
        with ThreadPoolExecutor(max_workers=paralelo) as executor:
            resultados = list(executor.map(gerar_secao, indices))
    else:
        resultados = [gerar_secao(i) for i in indices]

    personagens = {p.tag: p.descricao_visual for p in roteiro.personagens}
    cenas: list[dict] = []
    relogio = 0.0
    for lista in resultados:
        for cena in lista:
            numero = len(cenas) + 1
            cena = {"numero": numero, "id": nome_cena(numero), **cena}
            cena["inicio_s"] = round(relogio, 2)
            relogio += cena["duracao"]
            cena["fim_s"] = round(relogio, 2)
            cena["prompt"] = montar_prompt(cena["prompt_base"], personagens, estilo)
            cenas.append(cena)
    return cenas


# ---------------------------------------------------------------- exportação

def plano_completo(roteiro: Roteiro, cenas: list[dict], ritmo: str, palavras_por_minuto: float, estilo: str,
                   negativo: str) -> dict[str, Any]:
    return {
        "versao": 1,
        "titulo": roteiro.titulo,
        "ritmo": ritmo,
        "palavras_por_minuto": palavras_por_minuto,
        "duracao_total": round(sum(c["duracao"] for c in cenas), 2),
        "estilo": estilo,
        "negativo": negativo,
        "personagens": [p.__dict__ for p in roteiro.personagens],
        "cenas": cenas,
    }


def _animacoes_legiveis(cena: dict) -> str:
    if not cena.get("animacoes"):
        return "(só câmera)"
    return " · ".join(f"{a['elemento']} ({a['animacao']})" for a in cena["animacoes"])


def pedido_de_animacao(cena: dict) -> str:
    """Texto que o comando `animar` usa quando você não diz o que animar."""
    return ", ".join(f"{a['elemento']}: {a['animacao']}" for a in cena.get("animacoes", []))


def markdown_cenas(plano: dict, sufixo_midjourney: str = "") -> str:
    cenas = plano["cenas"]
    media = plano["duracao_total"] / max(1, len(cenas))
    linhas = [
        f"# Cenas — {plano['titulo']}", "",
        f"**{len(cenas)} cenas**, duração estimada **{formatar_tempo(plano['duracao_total'])}** "
        f"(média de {media:.1f} s por cena, ritmo {plano['ritmo']}).", "",
        "Gere uma imagem por cena e salve na pasta `imagens/` com o nome da cena (`cena01.png`, `cena02.png`...). "
        "Depois rode `animacao2d animar cena01` (ou `animacao2d animar --todas`).", "",
        "**Estilo** (já incluído no fim de cada prompt):", "", f"> {plano['estilo']}", "",
        f"**Prompt negativo** (para ferramentas que aceitam): `{plano['negativo']}`", "",
    ]
    if sufixo_midjourney:
        linhas += [f"**Midjourney**: acrescente `{sufixo_midjourney}` no fim de cada prompt.", ""]
    if plano.get("personagens"):
        linhas += ["## Personagens (para manter a consistência)", ""]
        for p in plano["personagens"]:
            linhas.append(f"- **{p['tag']}** — {p['nome']}: {p['descricao_visual']}")
        linhas.append("")
    secao_atual = None
    for cena in cenas:
        if cena["secao"] != secao_atual:
            secao_atual = cena["secao"]
            linhas += [f"## Seção {cena['secao']}: {cena['secao_titulo']}", ""]
        aviso = ""
        ritmo = config.RITMOS.get(plano["ritmo"])
        if ritmo and cena["duracao"] > ritmo.maximo_s * 1.3:
            aviso = " ⚠ longa — considere dividir em duas imagens"
        linhas += [
            f"### {cena['id']} · {formatar_tempo(cena['inicio_s'])}–{formatar_tempo(cena['fim_s'])} "
            f"({cena['duracao']:.1f} s) · plano {cena['plano']}{aviso}", "",
            f"**Narração:** {cena['narracao']}", "",
            f"**O que aparece:** {cena['descricao']}" + (f" — *{cena['expressao']}*" if cena.get("expressao") else ""),
            "",
            "**Prompt:**", "", "```", cena["prompt"], "```", "",
            f"**Animações:** {_animacoes_legiveis(cena)} · câmera: {cena['camera']}",
        ]
        if cena.get("texto_na_tela"):
            linhas.append(f"**Texto na tela (edição):** {cena['texto_na_tela']}")
        linhas.append("")
    return "\n".join(linhas)


def markdown_animacoes(plano: dict) -> str:
    linhas = [f"# Animações por cena — {plano['titulo']}", "",
              "Marque conforme for animando. O comando `animacao2d animar cenaXX` já usa esta lista; "
              "para mudar, passe o pedido: `animacao2d animar cena01 \"braço, olho, sol\"`.", ""]
    for cena in plano["cenas"]:
        linhas.append(f"- [ ] **{cena['id']}** ({cena['duracao']:.1f} s) — {_animacoes_legiveis(cena)} "
                      f"· câmera {cena['camera']}")
    return "\n".join(linhas) + "\n"


def texto_prompts(plano: dict, sufixo_midjourney: str = "") -> str:
    sufixo = f" {sufixo_midjourney}" if sufixo_midjourney else ""
    return "\n".join(f"{c['id']}: {c['prompt']}{sufixo}" for c in plano["cenas"]) + "\n"


def csv_prompts(plano: dict) -> str:
    saida = io.StringIO()
    escritor = csv.writer(saida)
    escritor.writerow(["cena", "inicio", "duracao_s", "prompt", "negativo", "animacoes", "camera", "narracao"])
    for c in plano["cenas"]:
        escritor.writerow([c["id"], formatar_tempo(c["inicio_s"]), c["duracao"], c["prompt"], plano["negativo"],
                           pedido_de_animacao(c), c["camera"], c["narracao"].replace("\n", " ")])
    return saida.getvalue()


def markdown_narracao(plano: dict) -> str:
    linhas = [f"# Narração por cena — {plano['titulo']}", "",
              "Dica: gere/grave um áudio por cena e salve em `audio/cena01.mp3`... — a animação usa a duração "
              "real e sincroniza a boca de quem fala.", ""]
    for c in plano["cenas"]:
        linhas += [f"**{c['id']}** [{formatar_tempo(c['inicio_s'])}]", "", c["narracao"], ""]
    return "\n".join(linhas)


def srt_legendas(plano: dict, maximo_caracteres: int = 84) -> str:
    blocos = []
    indice = 1
    for c in plano["cenas"]:
        texto = " ".join(re.sub(r"^[A-Z][A-Z0-9_]{1,24}:\s*", "", linha) for linha in c["narracao"].splitlines())
        palavras = texto.split()
        # divide em partes de tamanho parecido (evita sobrar uma palavra sozinha)
        quantidade = max(1, -(-len(texto) // maximo_caracteres))
        alvo = len(texto) / quantidade
        grupos, atual = [], []
        for palavra in palavras:
            if atual and len(grupos) < quantidade - 1 and len(" ".join(atual + [palavra])) > alvo * 1.05:
                grupos.append(atual)
                atual = []
            atual.append(palavra)
        if atual:
            grupos.append(atual)
        total_palavras = max(1, len(palavras))
        inicio = c["inicio_s"]
        for grupo in grupos:
            fim = inicio + c["duracao"] * len(grupo) / total_palavras
            blocos.append(f"{indice}\n{formatar_srt(inicio)} --> {formatar_srt(fim)}\n{' '.join(grupo)}\n")
            indice += 1
            inicio = fim
    return "\n".join(blocos)
