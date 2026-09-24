"""Especificação da animação de uma cena (arquivo cenaXX.json).

Coordenadas sempre em pixels da imagem ORIGINAL (a que você gerou), com a
origem no canto superior esquerdo: caixa = [x0, y0, x1, y1], pivo = [x, y].
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from animacao2d.animacao.catalogo import ANIMACOES, CAMERA_PADRAO, resolver_animacao, resolver_camera
from animacao2d.util import ler_json, salvar_json

MASCARAS = ("auto", "caixa", "elipse")
DIRECOES = ("", "direita", "esquerda", "cima", "baixo", "horario", "antihorario")


class ErroSpec(ValueError):
    pass


def _numeros(valor: Any, quantidade: int, campo: str) -> tuple[float, ...]:
    if not isinstance(valor, (list, tuple)) or len(valor) != quantidade:
        raise ErroSpec(f"'{campo}' precisa ter {quantidade} números, recebi: {valor!r}")
    try:
        return tuple(float(v) for v in valor)
    except (TypeError, ValueError) as erro:
        raise ErroSpec(f"'{campo}' tem valores inválidos: {valor!r}") from erro


def normalizar_animacoes(valor: Any) -> list[str]:
    if isinstance(valor, str):
        itens = [p for p in valor.replace("+", ",").split(",") if p.strip()]
    elif isinstance(valor, (list, tuple)):
        itens = [str(v) for v in valor]
    else:
        raise ErroSpec(f"Animação inválida: {valor!r}")
    nomes: list[str] = []
    for item in itens:
        nome = resolver_animacao(item.strip())
        if not nome:
            raise ErroSpec(f"Animação desconhecida: '{item.strip()}'. Opções: {', '.join(ANIMACOES)}")
        if nome not in nomes:
            nomes.append(nome)
    if not nomes:
        raise ErroSpec("Cada parte precisa de pelo menos uma animação.")
    return nomes


@dataclass
class Parte:
    nome: str
    animacoes: list[str]
    caixa: tuple[float, float, float, float]
    pivo: tuple[float, float] | None = None
    mascara: str = "auto"
    intensidade: float = 1.0
    velocidade: float = 1.0
    atraso: float = 0.0
    direcao: str = ""

    def __post_init__(self) -> None:
        x0, y0, x1, y1 = self.caixa
        self.caixa = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        if self.mascara not in MASCARAS:
            raise ErroSpec(f"Máscara '{self.mascara}' inválida para '{self.nome}'. Use: {', '.join(MASCARAS)}")
        if self.direcao not in DIRECOES:
            raise ErroSpec(f"Direção '{self.direcao}' inválida para '{self.nome}'. Use: {', '.join(DIRECOES[1:])}")

    @property
    def largura(self) -> float:
        return self.caixa[2] - self.caixa[0]

    @property
    def altura(self) -> float:
        return self.caixa[3] - self.caixa[1]

    def pivo_efetivo(self) -> tuple[float, float]:
        """Pivô informado ou o padrão da primeira animação que usa pivô."""
        if self.pivo is not None:
            return self.pivo
        x0, y0, x1, y1 = self.caixa
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        for nome in self.animacoes:
            tipo = ANIMACOES[nome].pivo
            if tipo == "base":
                return (cx, y1)
            if tipo == "topo":
                return (cx, y0)
            if tipo == "manual":
                return (cx, y1)
        return (cx, cy)

    @classmethod
    def de_dict(cls, dados: dict[str, Any]) -> "Parte":
        nome = str(dados.get("nome") or "parte").strip()
        bruto = dados.get("animacoes", dados.get("animacao"))
        if bruto is None:
            raise ErroSpec(f"A parte '{nome}' não tem 'animacoes'.")
        pivo = dados.get("pivo")
        return cls(
            nome=nome,
            animacoes=normalizar_animacoes(bruto),
            caixa=_numeros(dados.get("caixa"), 4, f"{nome}.caixa"),  # type: ignore[arg-type]
            pivo=_numeros(pivo, 2, f"{nome}.pivo") if pivo is not None else None,  # type: ignore[arg-type]
            mascara=str(dados.get("mascara") or "auto"),
            intensidade=float(dados.get("intensidade", 1.0)),
            velocidade=float(dados.get("velocidade", 1.0)),
            atraso=float(dados.get("atraso", 0.0)),
            direcao=str(dados.get("direcao") or ""),
        )

    def para_dict(self) -> dict[str, Any]:
        dados: dict[str, Any] = {
            "nome": self.nome,
            "animacoes": list(self.animacoes),
            "caixa": [round(v, 1) for v in self.caixa],
        }
        if self.pivo is not None:
            dados["pivo"] = [round(v, 1) for v in self.pivo]
        dados["mascara"] = self.mascara
        dados["intensidade"] = self.intensidade
        dados["velocidade"] = self.velocidade
        dados["atraso"] = self.atraso
        if self.direcao:
            dados["direcao"] = self.direcao
        return dados


@dataclass
class Camera:
    movimento: str = CAMERA_PADRAO
    intensidade: float = 1.0
    foco: tuple[float, float] | None = None

    @classmethod
    def de_dict(cls, dados: Any) -> "Camera":
        if dados is None:
            return cls()
        if isinstance(dados, str):
            return cls(movimento=resolver_camera(dados))
        foco = dados.get("foco")
        return cls(
            movimento=resolver_camera(dados.get("movimento")),
            intensidade=float(dados.get("intensidade", 1.0)),
            foco=_numeros(foco, 2, "camera.foco") if foco is not None else None,  # type: ignore[arg-type]
        )

    def para_dict(self) -> dict[str, Any]:
        dados: dict[str, Any] = {"movimento": self.movimento, "intensidade": self.intensidade}
        if self.foco is not None:
            dados["foco"] = [round(v, 1) for v in self.foco]
        return dados


@dataclass
class SpecCena:
    imagem: str
    largura: int
    altura: int
    duracao: float = 5.0
    camera: Camera = field(default_factory=Camera)
    partes: list[Parte] = field(default_factory=list)
    cena: int | None = None
    observacao: str = ""

    def caminho_imagem(self, base: Path) -> Path:
        caminho = Path(self.imagem)
        return caminho if caminho.is_absolute() else (base / caminho)

    def ajustar_tamanho(self, largura: int, altura: int) -> None:
        """Reescala coordenadas se a imagem foi trocada por outra de tamanho diferente."""
        if (largura, altura) == (self.largura, self.altura) or not self.largura or not self.altura:
            self.largura, self.altura = largura, altura
            return
        fx, fy = largura / self.largura, altura / self.altura
        for parte in self.partes:
            x0, y0, x1, y1 = parte.caixa
            parte.caixa = (x0 * fx, y0 * fy, x1 * fx, y1 * fy)
            if parte.pivo:
                parte.pivo = (parte.pivo[0] * fx, parte.pivo[1] * fy)
        if self.camera.foco:
            self.camera.foco = (self.camera.foco[0] * fx, self.camera.foco[1] * fy)
        self.largura, self.altura = largura, altura

    @classmethod
    def de_dict(cls, dados: dict[str, Any]) -> "SpecCena":
        if not isinstance(dados, dict):
            raise ErroSpec("O arquivo de animação precisa ser um objeto JSON.")
        partes = [Parte.de_dict(p) for p in dados.get("partes", [])]
        duracao = float(dados.get("duracao", 5.0))
        if duracao <= 0:
            raise ErroSpec("'duracao' precisa ser maior que zero.")
        return cls(
            imagem=str(dados.get("imagem", "")),
            largura=int(dados.get("largura", 0)),
            altura=int(dados.get("altura", 0)),
            duracao=duracao,
            camera=Camera.de_dict(dados.get("camera")),
            partes=partes,
            cena=dados.get("cena"),
            observacao=str(dados.get("observacao", "")),
        )

    def para_dict(self) -> dict[str, Any]:
        dados: dict[str, Any] = {"versao": 1}
        if self.cena is not None:
            dados["cena"] = self.cena
        dados.update(
            {
                "imagem": self.imagem,
                "largura": self.largura,
                "altura": self.altura,
                "duracao": round(self.duracao, 2),
                "camera": self.camera.para_dict(),
                "partes": [p.para_dict() for p in self.partes],
            }
        )
        if self.observacao:
            dados["observacao"] = self.observacao
        return dados

    @classmethod
    def carregar(cls, caminho: str | Path) -> "SpecCena":
        try:
            return cls.de_dict(ler_json(caminho))
        except ErroSpec as erro:
            raise ErroSpec(f"{caminho}: {erro}") from erro

    def salvar(self, caminho: str | Path) -> None:
        salvar_json(caminho, self.para_dict())
