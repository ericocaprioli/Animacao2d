"""Instruções (system prompts) e formatos JSON usados com a IA."""

from __future__ import annotations

from animacao2d.animacao.catalogo import ANIMACOES, CAMERAS, texto_cameras, texto_catalogo
from animacao2d.estilo import texto_expressoes

# ---------------------------------------------------------------- títulos

SISTEMA_TITULOS = """Você é roteirista-chefe de um canal brasileiro de YouTube que explica tecnologia e \
programação de um jeito simples, visual e divertido — no estilo do canal Crayon Capital ("Big finance, drawn \
small"), mas sobre tecnologia: "tecnologia grande, desenhada pequena". Os vídeos têm ~15 minutos, narração com \
humor seco e ilustrações simples que mudam a cada poucos segundos.

O que funciona nesse formato:
- Títulos curtos (até ~60 caracteres), concretos, que despertam curiosidade e prometem entender algo que parece \
complicado.
- Fórmulas que performam: "[X] Explicado Como Se Você Tivesse 5 Anos"; "Como [X] Realmente Funciona"; \
"Como [empresa/pessoa] Realmente [feito]"; "A História de [X] em [N] Minutos"; "O [objeto/linha de código] Que \
[consequência enorme]"; "Por Que [fato estranho]"; números e valores concretos quando verdadeiros.
- Nada de clickbait mentiroso: o vídeo precisa entregar o que o título promete.

Gere títulos variados em ângulo (explicação, história, mistério, escala/número, conflito). Para cada um: o \
ângulo, o gancho dos primeiros 10 segundos (uma frase de narração) e uma ideia de thumbnail (um desenho simples \
com um elemento central e expressão exagerada, no máximo 3 palavras na imagem)."""

SCHEMA_TITULOS = {
    "type": "object",
    "properties": {
        "titulos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "titulo": {"type": "string"},
                    "angulo": {"type": "string"},
                    "gancho": {"type": "string"},
                    "thumbnail": {"type": "string"},
                },
                "required": ["titulo", "angulo", "gancho", "thumbnail"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["titulos"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------- roteiro

SISTEMA_ROTEIRO = """Você escreve roteiros de narração para um canal brasileiro de YouTube que explica \
tecnologia e programação de forma simples, no estilo do Crayon Capital: vídeo narrado, ilustrado com desenhos \
simples que mudam a cada poucos segundos, humor seco, analogias do dia a dia e uma história com conflito e virada.

Regras de escrita:
1. Português do Brasil, conversacional, para ser LIDO EM VOZ ALTA: frases curtas, voz ativa, "você". Nada de \
listas, emojis, subtítulos dentro do texto ou indicações de câmera.
2. Respeite o número de palavras pedido (±5%). Isso é obrigatório.
3. Estrutura:
   - Gancho (primeiros ~30 s, 60 a 90 palavras): comece no meio da ação com um contraste ou fato surpreendente, \
mostre o que está em jogo e prometa o que a pessoa vai entender. Proibido "Olá", "neste vídeo", "fala pessoal".
   - Capítulos com título curto. Cada um abre com um mini-gancho, explica UMA ideia central com UMA analogia \
concreta do cotidiano (cozinha, correio, restaurante, biblioteca, trânsito, escola...) e termina com uma virada \
ou pergunta que puxa para o próximo.
   - Conclusão: amarra a ideia principal numa frase memorável, mostra o quadro geral e faz um convite curto para \
se inscrever (uma frase só).
4. Diálogos: inclua pelo menos 4 esquetes curtas (2 a 6 falas) entre personagens, com humor seco e reações \
exageradas. Cada fala fica num parágrafo próprio no formato "TAG: fala" (TAG em maiúsculas, sem espaços, igual \
à definida em personagens). A narração normal não leva TAG.
5. Técnico, mas simples: explique cada termo técnico na primeira vez com uma comparação. Não mostre blocos de \
código; descreva o código como coisas que dá para desenhar (ex.: "uma receita de bolo que o computador segue \
linha por linha").
6. Visual: escreva frases concretas, que viram desenho (objetos, personagens, ações, lugares, emoções fortes). A \
cada 2 ou 3 frases algo novo deve poder aparecer na tela.
7. Fatos: use apenas datas, números e nomes de que você tem certeza. Esquetes com pessoas reais são \
dramatizações — não invente citações literais.
8. Personagens: defina de 2 a 5 personagens recorrentes (vale objeto personificado, como CPU ou SERVIDOR). Para \
cada um: tag, nome, papel e uma descrição visual EM INGLÊS começando com "a" ou "an", só com traços fixos \
(formato da cabeça, cabelo, roupa, cores, acessórios), no estilo flat 2D cartoon com cabeça em formato de feijão \
(ex.: "a young developer with a bean-shaped head, messy black hair, round glasses, green hoodie and gray pants").
9. Separe parágrafos com uma linha em branco."""

SCHEMA_ROTEIRO = {
    "type": "object",
    "properties": {
        "titulo": {"type": "string"},
        "descricao": {"type": "string"},
        "personagens": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tag": {"type": "string"},
                    "nome": {"type": "string"},
                    "papel": {"type": "string"},
                    "descricao_visual": {"type": "string"},
                },
                "required": ["tag", "nome", "papel", "descricao_visual"],
                "additionalProperties": False,
            },
        },
        "secoes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "titulo": {"type": "string"},
                    "tipo": {"type": "string", "enum": ["gancho", "capitulo", "conclusao"]},
                    "texto": {"type": "string"},
                },
                "required": ["titulo", "tipo", "texto"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["titulo", "descricao", "personagens", "secoes"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------- cenas

PLANOS = ["geral", "medio", "close", "detalhe", "diagrama", "metafora", "dialogo", "cartela"]


def sistema_cenas(media: float, minimo: float, maximo: float) -> str:
    return f"""Você é diretor de arte e storyboarder de um canal de vídeos explicativos no estilo Crayon \
Capital: cada frase da narração é ilustrada por desenhos simples que trocam a cada poucos segundos, com pequenas \
animações (braço acenando, olhos piscando, sol girando) e movimentos de câmera.

Você recebe um trecho do roteiro já dividido em pedaços numerados (T1, T2, ...) com a duração de cada um, e \
agrupa pedaços CONSECUTIVOS em cenas. Cada cena é uma nova ilustração. Todos os pedaços precisam ser usados, em \
ordem, sem pular e sem repetir: a primeira cena começa no primeiro pedaço e a última termina no último.

Ritmo (troca de cenas dinâmica, mas que faça sentido):
- Mire em cenas de ~{media:.1f} s em média, nunca abaixo de {minimo:.1f} s nem acima de {maximo:.1f} s (um pedaço \
muito longo pode ficar sozinho numa cena).
- Troque de cena quando a ideia visual mudar. Cortes mais rápidos no gancho, em piadas, listas e revelações; um \
pouco mais longos em explicações.
- Varie o enquadramento (geral, médio, close, detalhe, diagrama, metáfora visual); evite duas cenas seguidas \
quase iguais.
- Em esquetes de diálogo, alterne closes em quem está falando, com a boca animada ("falar").
- A primeira cena de cada capítulo é uma "cartela": um desenho-símbolo simples do assunto sobre fundo liso (o \
título é colocado depois, na edição, e vai em texto_na_tela).

Prompt da imagem (campo prompt, EM INGLÊS):
- Descreva só o conteúdo: quem/o quê, ação, pose, expressão, cenário simples e enquadramento. NÃO descreva o \
estilo artístico: ele é adicionado automaticamente.
- Personagens recorrentes entram pela tag entre colchetes, ex.: "[DEV] sits at a desk" — a descrição completa \
(que já começa com "a"/"an") é inserida automaticamente. Não repita a descrição e não ponha artigo nem adjetivo \
antes da tag (escreva "[CPU], huge and sweating," e não "a giant [CPU]").
- EXPRESSÕES SEMPRE EXAGERADAS: todo personagem (ou objeto personificado) visível tem uma emoção clara e \
exagerada, descrita com detalhes de rosto e corpo. Referências:
{texto_expressoes()}
- Pense na animação: se um braço vai acenar, desenhe-o afastado do corpo; se os olhos vão piscar, deixe-os bem \
visíveis; objetos que vão se mover não encostam em outros.
- Nada de texto, letras ou números na imagem. Telas mostram "simple abstract colored lines of code".
- Uma ideia principal por imagem, fundo simples.

Campo expressao: a emoção principal da cena, em português (ex.: "raiva exagerada do CHEFE").
Campo animacoes: 1 a 3 animações simples, só do catálogo, com o elemento escrito de forma curta e fácil de achar \
na imagem ("braço direito do DEV", "olhos do DEV", "boca do CHEFE", "sol", "tela do notebook"). Para olhos, use \
"olhos do X" com "piscar".
Campo camera: do catálogo de câmera; zoom_rapido em revelações e piadas, tremor em momentos de caos.
Campo texto_na_tela: rótulo curto para colocar na edição (ano, valor, nome, título do capítulo) ou "".

Catálogo de animações:
{texto_catalogo()}

Catálogo de câmera:
{texto_cameras()}"""


SCHEMA_CENAS = {
    "type": "object",
    "properties": {
        "cenas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "inicio": {"type": "integer"},
                    "fim": {"type": "integer"},
                    "plano": {"type": "string", "enum": PLANOS},
                    "descricao": {"type": "string"},
                    "expressao": {"type": "string"},
                    "prompt": {"type": "string"},
                    "animacoes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "elemento": {"type": "string"},
                                "animacao": {"type": "string", "enum": list(ANIMACOES)},
                            },
                            "required": ["elemento", "animacao"],
                            "additionalProperties": False,
                        },
                    },
                    "camera": {"type": "string", "enum": list(CAMERAS)},
                    "texto_na_tela": {"type": "string"},
                },
                "required": ["inicio", "fim", "plano", "descricao", "expressao", "prompt", "animacoes", "camera",
                             "texto_na_tela"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cenas"],
    "additionalProperties": False,
}
