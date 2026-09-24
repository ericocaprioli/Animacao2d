# Animacao2d

Ferramenta em Python para produzir vídeos explicativos de tecnologia no estilo do canal
[Crayon Capital](https://www.youtube.com/@Crayon_Capital) ("big finance, drawn small"), só que
sobre código e tecnologia: ilustrações simples, trocas de cena dinâmicas, humor seco e pequenas
animações.

![Cena de exemplo animada](exemplos/demo.gif)

*A cena de exemplo: braço acenando (dobra no ombro), olhos piscando juntos, boca falando, sol
girando, nuvem deslizando, lâmpada brilhando, código sendo digitado na tela e zoom lento.*

## O que ela faz

1. **Títulos**: a partir de um tema, sugere títulos no formato que funciona nesse tipo de canal
   ("X Explicado Como Se Você Tivesse 5 Anos", "Como X Realmente Funciona"...). Você aprova um.
2. **Roteiro**: escreve a narração de ~15 minutos (~2.250 palavras), com gancho, capítulos,
   analogias do dia a dia e esquetes de diálogo. Você aprova, pede mudanças ou edita o arquivo.
3. **Cenas**: divide o roteiro em cenas (uma imagem cada) com troca dinâmica que acompanha a
   narração. Para cada cena gera:
   - o **prompt da imagem** em inglês, já com o estilo visual fixo, personagens consistentes,
     **expressões sempre exageradas** (raiva, alegria, susto...) e formato **16:9**;
   - a **lista de animações simples** (ex.: `cena01: braço do DEV (acenar), olhos (piscar)`);
   - movimento de câmera, tempo de início e fim, e o texto da narração.
4. **Animação**: você gera as imagens, salva como `cena01.png`, `cena02.png`... e roda
   `animacao2d animar cena01 "braço, olho, sol"`. A IA localiza cada parte na imagem, o motor
   recorta, preenche o fundo atrás e anima. Sai um MP4 1920x1080 (16:9) pronto para o editor.
5. **Editor visual** no navegador para corrigir caixas e pivôs, e **montagem** do vídeo completo
   (com a sua narração, se quiser).

## Instalação

Requisitos: **Python 3.10+**. O `ffmpeg` já vem junto (pacote `imageio-ffmpeg`), não precisa instalar.

```bash
git clone https://github.com/ericocaprioli/Animacao2d.git
cd Animacao2d
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -e .
```

Copie `.env.exemplo` para `.env` e preencha `ANTHROPIC_API_KEY` (chave em
[console.anthropic.com](https://console.anthropic.com/)). O `.env.exemplo` já vem com
`ANIMACAO2D_TEXTO=manual`: **títulos, roteiro e cenas você faz no claude.ai (sem custo de API)** e a
chave só é usada na animação, para localizar as partes nas imagens. Detalhes em
[Modo manual](#modo-manual-texto-no-claudeai-animação-pela-api).

Teste a instalação (não precisa de chave):

```bash
animacao2d exemplo
# gera exemplo_animacao2d/cena01.mp4 a partir da cena desenhada por código
```

## Passo a passo

### 1. Tema → título → roteiro → cenas

```bash
animacao2d novo "como funciona a internet"
```

O comando mostra os títulos sugeridos (com ângulo, gancho e ideia de thumbnail). Você escolhe o
número (ou digita o seu). Aí vem o roteiro e ele pergunta (no modo manual, cada etapa é um
copiar/colar no claude.ai, veja abaixo):

```
[a] aprovar e gerar as cenas   [r] reescrever com um pedido   [e] editei o roteiro.md, recarregar   [s] sair
```

Pode abrir `roteiro.md` em qualquer editor de texto, mudar o que quiser e escolher `e`. Depois da
aprovação ele gera as cenas.

Opções úteis: `--minutos 12`, `--ritmo rapido|medio|calmo`, `--titulo "Meu título"` (pula a
sugestão), `--paralelo 3` (gera as seções ao mesmo tempo, mais rápido).

Cada etapa também existe separada: `animacao2d titulos "tema"`, `animacao2d roteiro --pedido "mais
humor no capítulo 2"`, `animacao2d cenas`.

### 2. Arquivos do projeto

Tudo fica em `projetos/<nome-do-video>/`:

| Arquivo | Para que serve |
|---|---|
| `roteiro.md` | o roteiro (edite à vontade; falas no formato `DEV: fala`) |
| `cenas.md` | cada cena: tempo, narração, o que aparece, **prompt** e **animações** |
| `prompts.txt` | um prompt por linha (`cena01: ...`), para gerar em lote |
| `prompts.csv` | o mesmo em planilha (abre no Excel/Google Sheets) |
| `animacoes.md` | checklist das animações de cada cena |
| `narracao.md` | o texto de cada cena, para gravar ou gerar a voz |
| `legendas.srt` | legendas com os tempos estimados |
| `projeto.json` | título, ritmo e o **estilo visual** (editável) |
| `imagens/` | **coloque aqui** `cena01.png`, `cena02.png`... |
| `audio/` | opcional: `cena01.mp3`... (duração real e boca sincronizada) |
| `animacoes/` | `cena01.mp4`, `cena01.json` (ajustes) e `cena01_partes.png` (conferência) |
| `video/` | o vídeo montado |

### 3. Gerar as imagens (sempre 16:9)

Use o gerador que preferir; os prompts já pedem o estilo e o formato 16:9. Configure o formato
também na ferramenta:

| Ferramenta | Como deixar em 16:9 |
|---|---|
| Midjourney | já vem `--ar 16:9 --style raw` no fim de cada linha de `prompts.txt` |
| Leonardo.ai | proporção 16:9 (ex.: 1472x832) |
| ChatGPT / DALL·E | peça "formato paisagem 16:9" (1792x1024 serve) |
| Ideogram, Flux, SDXL | proporção 16:9 (1920x1080, 1344x768...) |

Se uma imagem não for 16:9, o programa avisa: ela é cortada para preencher o vídeo.

Dicas:
- Salve com o nome da cena: `cena01.png`, `cena1.jpg` e `Cena 01.webp` também funcionam.
- Para os personagens ficarem iguais em todas as cenas, use a mesma seed ou a referência de
  personagem da ferramenta (ex.: `--cref` no Midjourney). As descrições fixas de cada personagem
  já vão dentro dos prompts.
- Braços afastados do corpo, olhos visíveis e objetos que não se encostam deixam o recorte muito
  melhor; os prompts já pedem isso.

### 4. Animar

```bash
animacao2d animar cena01                        # usa a lista de animações planejada para a cena
animacao2d animar cena01 "braço, olho, sol"     # você diz o que animar
animacao2d animar cena01 "braço:acenar, sol:girar+pulsar, nuvem:deslizar"
animacao2d animar --todas                       # todas as cenas que já têm imagem
```

- A IA olha a imagem, encontra cada parte (braço, olhos, sol...) e o pivô (ombro, centro...).
- O resultado vai para `animacoes/cena01.mp4`. Confira `animacoes/cena01_partes.png`: cada parte
  aparece colorida exatamente como foi recortada.
- Rodar de novo **não** chama a IA outra vez: reaproveita os ajustes de `animacoes/cena01.json`.
  Para localizar de novo: `--redetectar`.
- Outras opções: `--duracao 6`, `--camera zoom_rapido`, `--previa` (960x540, rápido),
  `--sem-ia` (cria caixas para você posicionar no editor), `--forcar` (com `--todas`, refaz tudo).

Também funciona com uma imagem solta, fora de projeto:

```bash
animacao2d animar minha_imagem.png "olho, boca, braço"
```

### 5. Ajustar no editor visual

```bash
animacao2d editor
```

Abre o navegador com a lista de cenas. Na imagem você arrasta as caixas, redimensiona pelos cantos
e move o **pivô** (o ponto branco: ombro do braço, centro do sol...). No painel escolhe as
animações, a intensidade, a velocidade, quando começa (`Começa em`), a câmera e a duração. Botões:
**Localizar partes na imagem** (IA), **Ver recortes**, **Prévia rápida** e **Render 1080p**.
Atalhos: `N` nova parte, `M` ver recortes, `Del` apaga, `Ctrl+S` salva.

Funciona também numa pasta de imagens soltas: `animacao2d editor minha_pasta/`.

### 6. Montar o vídeo

```bash
animacao2d montar                           # video/video_completo.mp4 com todas as cenas
animacao2d montar --audio narracao.mp3      # as cenas se ajustam à duração da sua narração
animacao2d montar --previa                  # versão rápida 960x540
```

Com um áudio por cena em `audio/cena01.mp3`, `audio/cena02.mp3`... cada cena dura exatamente o
seu áudio e a boca (`falar`) abre e fecha no ritmo da voz. Cenas sem imagem viram uma tela cinza
com o nome da cena, para você ver o que falta. Se preferir montar no CapCut/Premiere/DaVinci, use
os `animacoes/cenaXX.mp4` direto (H.264, 1920x1080, 30 fps).

`animacao2d status` mostra o andamento (imagens que faltam, cenas animadas...).

## Animações disponíveis

| Animação | O que faz | Bom para |
|---|---|---|
| `piscar` | pisca de tempos em tempos (olhos próximos piscam juntos) | olhos (uma parte por olho) |
| `falar` | abre e fecha a boca (sincroniza com `audio/cenaXX`) | boca |
| `acenar` | vai e volta a partir do pivô, dobrando perto dele | braço, mão |
| `balancar` | balanço lento a partir do pivô | perna, cabeça, árvore, placa, rabo |
| `girar` | rotação contínua (`direcao`: horario/antihorario) | sol, engrenagem, roda, ventilador |
| `pulsar` | cresce e volta, como uma batida | coração, ícone, botão, alerta |
| `flutuar` | sobe e desce devagar | nuvem, moeda, balão, ícone |
| `deslizar` | atravessa a cena (`direcao`: direita/esquerda/cima/baixo) | nuvem, carro, pássaro |
| `tremer` | tremida nervosa | personagem assustado, alarme |
| `aparecer` | surge com um "pop" elástico (use `Começa em`) | ícones, setas, objetos que entram |
| `respirar` | respiração sutil | personagem inteiro |
| `brilhar` | brilho pulsante com halo | lâmpada, estrela, tela, fogo |
| `ondular` | distorção em onda | bandeira, água, fogo, cabelo |
| `codigo` | linhas de código sendo digitadas | tela de computador ou celular |

Dá para combinar na mesma parte: `sol:girar+pulsar`, `lâmpada:brilhar+flutuar`. Também entende
verbos: `"o braço acenando e os olhos piscando"`.

Câmeras: `zoom_in` (padrão), `zoom_out`, `pan_esquerda`, `pan_direita`, `pan_cima`, `pan_baixo`,
`zoom_rapido` (revelação/piada), `tremor` (caos), `parado`. Lista completa: `animacao2d animacoes`.

## Ritmo das cenas

| Ritmo | Troca de imagem | Imagens em 15 min |
|---|---|---|
| `rapido` | ~3,5 s (como o Crayon Capital) | ~250 |
| `medio` (padrão) | ~5 s | ~180 |
| `calmo` | ~7,5 s | ~120 |

A IA não corta em tempos fixos: agrupa as frases da narração e troca de imagem quando a ideia
visual muda. Cortes mais rápidos no gancho, em piadas e revelações; mais longos em explicações.
Cada capítulo começa com uma "cartela" (desenho-símbolo; o título você põe na edição).

## Estilo visual e expressões

O estilo vai no fim de todo prompt e fica em `projeto.json` (`estilo` e `negativo`): vetor 2D
chapado, contorno preto, personagens de cabeça em formato de feijão, paleta dessaturada com uma
cor de destaque, **expressões exageradas** e formato **16:9**. Mudou o estilo? Rode
`animacao2d exportar` para refazer `cenas.md`, `prompts.txt` etc. com o estilo novo.

Toda cena descreve a emoção de cada personagem de forma exagerada (raiva: sobrancelhas enormes,
rosto vermelho, fumaça saindo das orelhas; alegria: sorrisão, braços para cima; susto: olhos do
tamanho de pratos, queixo no chão...). O guia completo está em `animacao2d/estilo.py`.

## Modo manual (texto no claude.ai, animação pela API)

Com `ANIMACAO2D_TEXTO=manual` no `.env` (ou `--manual` no comando), títulos, roteiro e cenas não
usam a API. Em cada etapa:

1. O programa abre o arquivo do pedido (`projetos/<video>/_manual/<etapa>_pedido.txt`).
   Copie tudo (Ctrl+A, Ctrl+C) e cole numa conversa do [claude.ai](https://claude.ai).
2. Copie a resposta do Claude (o botão de copiar do bloco de código) e **cole no terminal**.
   Aperte Enter numa linha vazia. Se preferir, salve a resposta em
   `_manual/<etapa>_resposta.json` e aperte Enter.
3. Se a resposta vier fora do formato, o programa avisa e pede para colar de novo.

Num vídeo de 15 minutos são umas 10 rodadas: 1 de títulos, 1 de roteiro (mais uma a cada
reescrita) e 1 por seção nas cenas. Só o primeiro pedido de cenas é longo, porque leva o roteiro
inteiro; os seguintes são curtos e vão **na mesma conversa** (o arquivo avisa). Se abrir uma
conversa nova, use o `_pedido_completo.txt` da seção. O pedido é texto comum, então também funciona
em outros chats.

A **animação** (`animar`, e o botão "Localizar partes" do editor) sempre usa a API. Sem chave
nenhuma, use `animacao2d animar cena01 "braço, olho" --sem-ia` e posicione as partes no editor.
Para um projeto em modo manual usar a API no texto, passe `--api`.

## Custos e modelo

- **Modo manual** (padrão do `.env.exemplo`): o texto não custa nada de API. A animação custa em
  torno de US$ 0,05 por cena com `claude-opus-5` (cerca de US$ 9 para ~180 cenas). A IA só é
  chamada na primeira vez de cada cena; renderizar de novo é grátis.
- **Tudo pela API**: some cerca de US$ 1–3 por vídeo para títulos, roteiro e cenas.
- Os valores são estimativas. Para baratear a animação, teste `ANIMACAO2D_MODELO_VISAO=claude-sonnet-5`.
- A assinatura do claude.ai (Pro/Max) não inclui créditos de API: são cobranças separadas. As chamadas usam cache de prompt e, se
o modelo recusar um pedido por engano, a API refaz automaticamente com um modelo substituto
(`fallbacks`).

## Dicas para as animações ficarem boas

- Confira sempre o `cenaXX_partes.png` (ou **Ver recortes** no editor).
- Braço: a caixa vai do ombro até a ponta dos dedos, e o pivô fica no ombro. Perto do pivô o
  braço quase não se mexe, então ele "dobra" de forma natural.
- Olhos: uma parte por olho, caixa justa. A piscada detecta a pupila sozinha.
- Recorte `auto` falhou (aparece o aviso)? Troque para `elipse` (coisas redondas) ou `caixa`, ou
  ajuste a caixa para envolver só a peça.
- Intensidade e velocidade vão de 0 a 3 (1 = padrão).

## Estrutura do código

```
animacao2d/
  cli.py            linha de comando
  fluxo.py          etapas (roteiro, cenas, preparar e renderizar cenas)
  llm.py            Claude API (JSON estruturado, streaming, fallback) e modo manual
  prompts.py        instruções para a IA (títulos, roteiro, cenas)
  roteiro.py        títulos e roteiro (roteiro.md <-> estrutura)
  cenas.py          divisão em trechos/cenas e exportações (md, txt, csv, srt)
  estilo.py         estilo visual padrão e guia de expressões exageradas
  projeto.py        pasta do projeto
  montagem.py       vídeo completo + áudio
  animacao/
    catalogo.py     animações e câmeras
    pedido.py       entende "braço, olho, sol"
    detectar.py     localização das partes com o Claude (visão)
    spec.py         arquivo de ajustes de cada cena (cenaXX.json)
    mascara.py      recorte das partes e reconstrução do fundo
    efeitos.py      piscar, falar, acenar, girar...
    camera.py       zoom/pan
    render.py       composição quadro a quadro
    video.py        gravação MP4 (H.264) e leitura de áudio
  editor/           editor visual (servidor local + página)
```

Testes (não usam internet nem gastam créditos; a API é simulada):

```bash
pip install -e ".[dev]"
pytest
```

## Problemas comuns

- **"Não consegui acessar a API"**: falta o `.env` com `ANTHROPIC_API_KEY` (ou use `--manual`).
- **Acentos estranhos no `prompts.csv`**: abra pelo Excel normalmente (o arquivo tem BOM UTF-8);
  no Google Sheets use Arquivo → Importar.
- **Editor não abre**: acesse o endereço que aparece no terminal (ex.: `http://127.0.0.1:8765/`);
  se a porta estiver ocupada, use `--porta 8800`.
- **Cena com imagem trocada**: se o tamanho mudou, as caixas são reescaladas; se o desenho mudou,
  rode `animacao2d animar cena05 --redetectar`.
