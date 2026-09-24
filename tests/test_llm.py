import json

import pytest

from animacao2d.llm import ClaudeIA, ErroIA, ManualIA, bloco_texto, validar_schema
from api_falsa import ApiFalsa

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}, "nome": {"type": "string", "enum": ["a", "b"]}},
          "required": ["ok", "nome"], "additionalProperties": False}


def test_pedido_formatado_para_a_api():
    api = ApiFalsa([{"ok": True, "nome": "a"}])
    ia = ClaudeIA(modelo="claude-opus-5", cliente=api.cliente())
    assert ia.gerar_json(tarefa="t", sistema="sistema", conteudo=[bloco_texto("oi")], schema=SCHEMA,
                         esforco="low") == {"ok": True, "nome": "a"}
    pedido, cabecalhos = api.pedidos[0], api.cabecalhos[0]
    assert pedido["model"] == "claude-opus-5"
    assert pedido["thinking"] == {"type": "adaptive"}
    assert pedido["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}}
    assert pedido["fallbacks"] == "default"
    assert pedido["stream"] is True
    assert pedido["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "server-side-fallback-2026-07-01" in cabecalhos["anthropic-beta"]


def test_recusa_e_corte_viram_erro_amigavel():
    for motivo in ("refusal", "max_tokens"):
        api = ApiFalsa([{"ok": True, "nome": "a"}], stop_reason=motivo)
        with pytest.raises(ErroIA):
            ClaudeIA(cliente=api.cliente()).gerar_json(tarefa="t", sistema="s", conteudo="oi", schema=SCHEMA)


def test_json_fora_do_formato():
    api = ApiFalsa([{"ok": "sim"}])
    with pytest.raises(ErroIA, match="JSON inesperado"):
        ClaudeIA(cliente=api.cliente()).gerar_json(tarefa="t", sistema="s", conteudo="oi", schema=SCHEMA)


def test_validar_schema():
    assert validar_schema({"ok": True, "nome": "a"}, SCHEMA) == []
    erros = validar_schema({"ok": 1, "nome": "z"}, SCHEMA)
    assert any("boolean" in e for e in erros) and any("fora das opções" in e for e in erros)


def test_modo_manual_por_arquivo(tmp_path, monkeypatch):
    ia = ManualIA(tmp_path, abrir_arquivo=False)
    resposta = tmp_path / "_manual" / "titulos_resposta.json"

    def responder(_pergunta=""):
        resposta.write_text("```json\n" + json.dumps({"ok": False, "nome": "b"}) + "\n```", encoding="utf-8")
        return ""

    monkeypatch.setattr("builtins.input", responder)
    dados = ia.gerar_json(tarefa="titulos", sistema="REGRAS", conteudo=[bloco_texto("TAREFA")], schema=SCHEMA)
    assert dados == {"ok": False, "nome": "b"}
    pedido = (tmp_path / "_manual" / "titulos_pedido.txt").read_text(encoding="utf-8")
    assert "REGRAS" in pedido and "TAREFA" in pedido and "JSON Schema" in pedido


def test_modo_ia_padrao(monkeypatch):
    from animacao2d.llm import modo_ia

    for variavel in ("ANIMACAO2D_IA", "ANIMACAO2D_TEXTO", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(variavel, raising=False)
    assert modo_ia() == "manual"  # sem chave: grátis
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-teste")
    assert modo_ia() == "api"
    monkeypatch.setenv("ANIMACAO2D_IA", "manual")
    assert modo_ia() == "manual"  # o .env manda


def _colar(monkeypatch, linhas):
    fila = list(linhas)

    def entrada(_pergunta=""):
        if not fila:
            raise EOFError
        return fila.pop(0)

    monkeypatch.setattr("builtins.input", entrada)


def test_modo_manual_colando_no_terminal(tmp_path, monkeypatch):
    # resposta como vem do claude.ai: texto antes, linha vazia, bloco de código, linha vazia final
    resposta = ["Aqui está:", "", "```json", "{", '  "ok": true,', '  "nome": "a"', "}", "```", ""]
    _colar(monkeypatch, resposta)
    ia = ManualIA(tmp_path, abrir_arquivo=False)
    assert ia.gerar_json(tarefa="t1", sistema="s", conteudo="x", schema=SCHEMA) == {"ok": True, "nome": "a"}
    # guarda a resposta colada
    assert json.loads((tmp_path / "_manual" / "t1_resposta.json").read_text(encoding="utf-8"))["nome"] == "a"


def test_modo_manual_json_invalido_pede_de_novo(tmp_path, monkeypatch, capsys):
    _colar(monkeypatch, ['{"ok": "sim", "nome": "a"}', "", '{"ok": false, "nome": "b"}', ""])
    ia = ManualIA(tmp_path, abrir_arquivo=False)
    assert ia.gerar_json(tarefa="t", sistema="s", conteudo="x", schema=SCHEMA) == {"ok": False, "nome": "b"}
    assert "formato esperado" in capsys.readouterr().out


def test_modo_manual_continuacao_na_mesma_conversa(tmp_path, monkeypatch):
    _colar(monkeypatch, ['{"ok": true, "nome": "a"}', "", '{"ok": true, "nome": "b"}', ""])
    ia = ManualIA(tmp_path, abrir_arquivo=False)
    contexto = bloco_texto("ROTEIRO INTEIRO " * 50, cache=True)
    ia.gerar_json(tarefa="cenas_secao01", sistema="REGRAS", conteudo=[contexto, bloco_texto("SEÇÃO 1")], schema=SCHEMA)
    ia.gerar_json(tarefa="cenas_secao02", sistema="REGRAS", conteudo=[contexto, bloco_texto("SEÇÃO 2")], schema=SCHEMA)
    primeiro = (tmp_path / "_manual" / "cenas_secao01_pedido.txt").read_text(encoding="utf-8")
    segundo = (tmp_path / "_manual" / "cenas_secao02_pedido.txt").read_text(encoding="utf-8")
    assert "ROTEIRO INTEIRO" in primeiro and "REGRAS" in primeiro
    assert "MESMA conversa" in segundo and "SEÇÃO 2" in segundo
    assert "ROTEIRO INTEIRO" not in segundo and "REGRAS" not in segundo
    assert (tmp_path / "_manual" / "cenas_secao02_pedido_completo.txt").is_file()


def test_modo_manual_localizar_partes_pede_para_anexar_imagem(tmp_path, monkeypatch, capsys, imagem_exemplo):
    from animacao2d.animacao.detectar import detectar_partes

    resposta = {"partes": [{"nome": "sol", "animacoes": ["girar"], "caixa": [780, 43, 924, 300], "pivo": [852, 172],
                            "direcao": "", "observacao": ""}], "nao_encontrados": ["foguete"], "camera": "zoom_in"}
    _colar(monkeypatch, [json.dumps(resposta), ""])
    partes, faltando, camera = detectar_partes(ManualIA(tmp_path, abrir_arquivo=False), imagem_exemplo, "sol, foguete")
    saida = capsys.readouterr().out
    assert "anexe a imagem" in saida and "cena01.png" in saida
    pedido = (tmp_path / "_manual" / "animar_cena01_pedido.txt").read_text(encoding="utf-8")
    assert "MILÉSIMOS" in pedido and "1456x816" in pedido
    # milésimos -> pixels da imagem original (1456x816)
    assert [round(v) for v in partes[0].caixa] == [1136, 35, 1345, 245]
    assert faltando == ["foguete"] and camera == "zoom_in"
