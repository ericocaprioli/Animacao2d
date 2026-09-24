"""Estilo visual padrão dos prompts de imagem (inspirado no visual do Crayon Capital).

O texto é adicionado ao final de TODO prompt de cena, garantindo que as
imagens saiam com a mesma cara. Cada projeto guarda uma cópia editável em
projeto.json ("estilo" e "negativo").
"""

ESTILO_PADRAO = (
    "flat 2D vector cartoon illustration, minimalist explainer-video style, clean smooth medium-weight black "
    "outlines, simple rounded shapes, characters with large bean-shaped heads, simple expressive eyes, "
    "thick simple limbs, EXAGGERATED cartoon facial expressions and body language, "
    "muted desaturated color palette (warm grays, soft browns, dusty blues, off-white) with one bright accent "
    "color, solid flat color fills, minimal shading, simple uncluttered background, 16:9 widescreen landscape "
    "format (YouTube), wide composition with empty space around the main subject, every character and object "
    "clearly separated from the others, arms and "
    "legs drawn away from the body, no text, no letters, no numbers, no watermark"
)

NEGATIVO_PADRAO = (
    "text, letters, words, numbers, captions, watermark, signature, logo, photorealistic, 3d render, "
    "heavy gradients, clutter, busy background, overlapping limbs, extra fingers, blurry, vertical format, "
    "portrait orientation, square format"
)

# Parâmetros sugeridos para quem usa Midjourney (vão no fim de cada linha de prompts.txt)
SUFIXO_MIDJOURNEY_PADRAO = "--ar 16:9 --style raw"

# Guia de expressões exageradas (usado nos prompts da IA e no README)
EXPRESSOES = {
    "raiva": "furious, huge angry slanted eyebrows, clenched teeth, bright red face, steam puffing from the ears, "
             "fists raised",
    "alegria": "ecstatic, enormous open-mouth grin, eyes squeezed shut with joy, arms thrown up in celebration",
    "surpresa": "shocked, eyes wide as dinner plates, jaw dropped almost to the floor, hair standing straight up",
    "medo": "terrified, trembling, huge round eyes with tiny pupils, sweat drops flying, hands pressed on cheeks",
    "tristeza": "devastated, streams of tears pouring down, droopy eyes, slumped shoulders, gray rain cloud above",
    "confusao": "completely baffled, one eyebrow raised high, crooked mouth, question marks floating around the head",
    "orgulho": "smug and overconfident, chin up, half-closed eyes, huge smirk, arms crossed",
    "desespero": "panicking, hands pulling hair, mouth wide open screaming, eyes spinning",
    "tedio": "bored to death, half-closed heavy eyelids, head melting onto the hand, long sigh cloud",
    "ideia": "eureka moment, eyes sparkling, finger raised, big grin, glowing light bulb above the head",
}


def texto_expressoes() -> str:
    return "\n".join(f"- {nome}: \"{descricao}\"" for nome, descricao in EXPRESSOES.items())
