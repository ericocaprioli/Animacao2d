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
        with pytest.raises(urllib.error.HTTPError):
            pedir("/api/cena/nao-existe")
    finally:
        servidor.shutdown()
        servidor.server_close()
