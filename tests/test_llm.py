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


def test_modo_manual(tmp_path, monkeypatch):
    ia = ManualIA(tmp_path)
    resposta = tmp_path / "_manual" / "titulos_resposta.json"

    def responder(_pergunta=""):
        resposta.write_text("```json\n" + json.dumps({"ok": False, "nome": "b"}) + "\n```", encoding="utf-8")
        return ""

    monkeypatch.setattr("builtins.input", responder)
    dados = ia.gerar_json(tarefa="titulos", sistema="REGRAS", conteudo=[bloco_texto("TAREFA")], schema=SCHEMA)
    assert dados == {"ok": False, "nome": "b"}
    pedido = (tmp_path / "_manual" / "titulos_pedido.md").read_text(encoding="utf-8")
    assert "REGRAS" in pedido and "TAREFA" in pedido and "JSON Schema" in pedido


def test_manual_nao_faz_visao(tmp_path):
    with pytest.raises(ErroIA):
        ManualIA(tmp_path).gerar_json(tarefa="d", sistema="s", conteudo="x", schema=SCHEMA, visao=True)
