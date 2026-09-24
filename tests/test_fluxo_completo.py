"""Fluxo de ponta a ponta com um servidor falso da API (sem internet, sem custo)."""

import json
import shutil
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import imageio_ffmpeg
import pytest

from animacao2d import cli
from animacao2d.projeto import Projeto
from servidor_falso import ServidorFalso


@pytest.fixture
def api(ambiente_isolado, monkeypatch):
    with ServidorFalso() as servidor:
        monkeypatch.setenv("ANTHROPIC_BASE_URL", servidor.url)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "teste")
        yield servidor


def _responder(monkeypatch, respostas):
    fila = list(respostas)
    monkeypatch.setattr("builtins.input", lambda _pergunta="": fila.pop(0) if fila else "")


def test_novo_animar_montar(api, ambiente_isolado, monkeypatch, imagem_exemplo, capsys):
    _responder(monkeypatch, ["1", "a"])  # escolhe o 1º título e aprova o roteiro
    assert cli.main(["novo", "como funciona a internet", "--minutos", "3"]) == 0
    projeto = Projeto.resolver()
    assert projeto.titulo == "A Internet Explicada Como Se Você Tivesse 5 Anos"
    assert projeto.dados["etapa"] == "cenas"
    plano = json.loads(projeto.cenas_json.read_text(encoding="utf-8"))
    assert len(plano["cenas"]) > 10
    primeira = plano["cenas"][0]
    assert primeira["id"] == "cena01"
    assert "a young developer" in primeira["prompt"]  # personagem substituído
    assert "EXAGGERATED" in primeira["prompt"]  # estilo com expressões exageradas
    for arquivo in (projeto.cenas_md, projeto.prompts_txt, projeto.prompts_csv, projeto.animacoes_md,
                    projeto.narracao_md, projeto.legendas_srt, projeto.roteiro_md):
        assert arquivo.is_file() and arquivo.stat().st_size > 0

    # o usuário gera a imagem e salva como cena01.png
    shutil.copy(imagem_exemplo, projeto.pasta_imagens / "cena01.png")
    assert cli.main(["animar", "cena01", "--previa", "--duracao", "1.5"]) == 0
    spec = json.loads(projeto.spec_da_cena(1).read_text(encoding="utf-8"))
    assert [p["nome"] for p in spec["partes"]] == ["braço direito do DEV", "olho esquerdo", "olho direito"]
    assert spec["imagem"] == "../imagens/cena01.png"
    quadros, _ = imageio_ffmpeg.count_frames_and_secs(str(projeto.video_da_cena(1)))
    assert quadros == 45
    assert projeto.previa_da_cena(1).is_file()

    # re-renderizar sem pedido não chama a IA de novo
    pedidos_antes = len(api.pedidos)
    assert cli.main(["animar", "cena01", "--previa", "--duracao", "1"]) == 0
    assert len(api.pedidos) == pedidos_antes

    assert cli.main(["status"]) == 0
    assert "Imagens: 1/" in capsys.readouterr().out


def test_animar_imagem_avulsa_sem_ia(ambiente_isolado, imagem_exemplo, capsys):
    imagem_exemplo.with_suffix(".json").unlink()
    assert cli.main(["animar", str(imagem_exemplo), "braço:acenar, sol:girar", "--sem-ia", "--previa",
                     "--duracao", "1"]) == 0
    spec = json.loads(imagem_exemplo.with_suffix(".json").read_text(encoding="utf-8"))
    assert [p["animacoes"] for p in spec["partes"]] == [["acenar"], ["girar"]]
    assert imagem_exemplo.with_suffix(".mp4").is_file()


def test_montar_com_cena_faltando(ambiente_isolado, imagem_exemplo):
    projeto = Projeto.criar("Teste de montagem")
    cenas = [{"numero": n, "id": f"cena{n:02d}", "duracao": 1.0, "camera": "zoom_in", "animacoes": []} for n in (1, 2)]
    projeto.cenas_json.write_text(json.dumps({"cenas": cenas}), encoding="utf-8")
    shutil.copy(imagem_exemplo, projeto.pasta_imagens / "cena01.png")
    assert cli.main(["montar", "-p", str(projeto.pasta), "--previa"]) == 0
    quadros, segundos = imageio_ffmpeg.count_frames_and_secs(str(projeto.pasta_video / "previa.mp4"))
    assert quadros == 60 and segundos == pytest.approx(2.0, abs=0.05)


def test_editor_api(ambiente_isolado, imagem_exemplo):
    from animacao2d.editor.servidor import Editor, criar_tratador

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), criar_tratador(Editor(pasta_avulsa=imagem_exemplo.parent)))
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{servidor.server_address[1]}"

    def pedir(caminho, corpo=None):
        dados = None if corpo is None else json.dumps(corpo).encode()
        req = urllib.request.Request(base + caminho, data=dados, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resposta:
            return json.loads(resposta.read())

    try:
        assert "Animacao2d" in urllib.request.urlopen(base + "/").read().decode()
        estado = pedir("/api/estado")
        assert [c["id"] for c in estado["cenas"]] == ["cena01"]
        cena = pedir("/api/cena/cena01")
        assert cena["salvo"] and len(cena["spec"]["partes"]) == 8
        spec = cena["spec"]
        spec["partes"] = spec["partes"][:2]
        spec["duracao"] = 1.0
        assert pedir("/api/cena/cena01/salvar", {"spec": spec})["ok"]
        assert len(pedir("/api/cena/cena01")["spec"]["partes"]) == 2
        mascaras = pedir("/api/cena/cena01/mascaras", {"spec": spec})
        assert mascaras["modos"]["braço levantado"] == "auto"
        render = pedir("/api/cena/cena01/renderizar", {"spec": spec, "previa": True})
        assert render["video_url"].startswith("/arquivo/video/cena01")
        assert estado["modo_ia"] == "manual"  # sem chave de API: grátis
        texto = pedir("/api/cena/cena01/pedido_manual", {"pedido": "sol"})["texto"]
        assert "MILÉSIMOS" in texto and "cena01.png" in texto
        resposta = {"partes": [{"nome": "sol", "animacoes": ["girar"], "caixa": [780, 43, 924, 300],
                                "pivo": [852, 172], "direcao": "", "observacao": ""}],
                    "nao_encontrados": [], "camera": "zoom_in"}
        r = pedir("/api/cena/cena01/resposta_manual", {"texto": "```json\n" + json.dumps(resposta) + "\n```",
                                                       "pedido": "sol", "duracao": 1.0})
        assert [round(v) for v in r["spec"]["partes"][0]["caixa"]] == [1136, 35, 1345, 245]
        assert len(pedir("/api/cena/cena01")["spec"]["partes"]) == 1  # gravado
        with pytest.raises(urllib.error.HTTPError):
            pedir("/api/cena/cena01/detectar", {"pedido": "sol"})  # modo grátis não usa a API
        with pytest.raises(urllib.error.HTTPError):
            pedir("/api/cena/nao-existe")
    finally:
        servidor.shutdown()
        servidor.server_close()


def _usuario_do_claude_ai(colando: list[str], vistos: list[str]):
    """Simula você: lê o pedido gerado, "pergunta ao claude.ai" e cola a resposta no terminal."""
    from pathlib import Path

    from servidor_falso import resposta_cenas, resposta_deteccao, resposta_roteiro, resposta_titulos

    def usuario(pergunta=""):
        if colando:
            return colando.pop(0)
        if pergunta.strip() == ">":
            arquivo = max(Path("projetos").glob("**/_manual/*_pedido.txt"), key=lambda a: a.stat().st_mtime_ns)
            texto = arquivo.read_text(encoding="utf-8")
            vistos.append(arquivo.name)
            falso = {"messages": [{"content": [{"text": texto}]}]}
            if arquivo.name.startswith("titulos"):
                dados = resposta_titulos(falso)
            elif arquivo.name.startswith("roteiro"):
                dados = resposta_roteiro(falso)
            elif arquivo.name.startswith("animar"):
                dados = resposta_deteccao(falso)  # em pixels da imagem de exemplo (1456x816) -> milésimos
                for parte in dados["partes"]:
                    x0, y0, x1, y1 = parte["caixa"]
                    parte["caixa"] = [x0 * 1000 / 1456, y0 * 1000 / 816, x1 * 1000 / 1456, y1 * 1000 / 816]
                    parte["pivo"] = [parte["pivo"][0] * 1000 / 1456, parte["pivo"][1] * 1000 / 816]
            else:
                dados = resposta_cenas(falso)
            colando.extend(["Claro! Aqui está:", "", "```json",
                            *json.dumps(dados, ensure_ascii=False, indent=2).split("\n"), "```", ""])
            return colando.pop(0)
        if "Escolha o número" in pergunta:
            return "1"
        if "Opção" in pergunta:
            return "a"
        return ""

    return usuario


def test_tudo_gratis_sem_api(api, ambiente_isolado, monkeypatch, imagem_exemplo):
    """ANIMACAO2D_IA=manual: títulos, roteiro, cenas E localização das partes por copiar/colar; zero API."""
    monkeypatch.setenv("ANIMACAO2D_IA", "manual")
    vistos: list[str] = []
    monkeypatch.setattr("builtins.input", _usuario_do_claude_ai([], vistos))
    assert cli.main(["novo", "como funciona a internet", "--minutos", "3"]) == 0
    assert vistos[:2] == ["titulos_pedido.txt", "roteiro_pedido.txt"]
    assert [n for n in vistos if n.startswith("cenas")] == [f"cenas_secao{i:02d}_pedido.txt" for i in (1, 2, 3, 4)]

    projeto = Projeto.resolver()
    assert projeto.dados["ia_manual"] is True
    segundo = (projeto.pasta / "_manual" / "cenas_secao02_pedido.txt").read_text(encoding="utf-8")
    assert "MESMA conversa" in segundo  # só o primeiro pedido de cenas leva o roteiro inteiro
    assert len(json.loads(projeto.cenas_json.read_text(encoding="utf-8"))["cenas"]) > 10

    shutil.copy(imagem_exemplo, projeto.pasta_imagens / "cena01.png")
    assert cli.main(["animar", "cena01", "--previa", "--duracao", "1"]) == 0
    assert vistos[-1] == "animar_cena01_pedido.txt"
    spec = json.loads(projeto.spec_da_cena(1).read_text(encoding="utf-8"))
    assert [round(v) for v in spec["partes"][0]["caixa"]] == [348, 190, 478, 385]  # milésimos -> pixels
    assert projeto.video_da_cena(1).is_file()
    assert api.pedidos == []  # nada passou pela API


def test_projeto_gratis_pode_usar_api_na_animacao(api, ambiente_isolado, monkeypatch, imagem_exemplo):
    projeto = Projeto.criar("Híbrido")
    projeto.dados["ia_manual"] = True
    projeto.salvar()
    shutil.copy(imagem_exemplo, projeto.pasta_imagens / "cena01.png")
    assert cli.main(["animar", "cena01", "braço, olho", "--api", "--previa", "--duracao", "1"]) == 0
    assert len(api.pedidos) == 1 and "localiza" in api.pedidos[0]["system"][0]["text"]


def test_editor_abre_com_caixas_do_plano(ambiente_isolado, imagem_exemplo):
    from animacao2d.editor.servidor import Editor

    projeto = Projeto.criar("Plano")
    cena = {"numero": 1, "id": "cena01", "duracao": 2.0, "camera": "zoom_rapido", "descricao": "",
            "animacoes": [{"elemento": "braço do DEV", "animacao": "acenar"}, {"elemento": "olhos", "animacao": "piscar"}]}
    projeto.cenas_json.write_text(json.dumps({"cenas": [cena]}), encoding="utf-8")
    shutil.copy(imagem_exemplo, projeto.pasta_imagens / "cena01.png")
    dados = Editor(projeto=projeto).dados_cena("cena01")
    assert dados["provisorio"] and not dados["salvo"]
    assert [(p["nome"], p["animacoes"]) for p in dados["spec"]["partes"]] == [("braço do DEV", ["acenar"]),
                                                                             ("olhos", ["piscar"])]
    assert dados["spec"]["camera"]["movimento"] == "zoom_rapido"
    assert not projeto.spec_da_cena(1).exists()  # só grava quando você salvar
