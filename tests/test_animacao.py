import imageio_ffmpeg
import numpy as np
import pytest

from animacao2d.animacao.efeitos import Pose
from animacao2d.animacao.render import RenderizadorCena
from animacao2d.animacao.spec import ErroSpec, Parte, SpecCena


@pytest.fixture
def renderizador(imagem_exemplo):
    spec = SpecCena.carregar(imagem_exemplo.with_suffix(".json"))
    return RenderizadorCena(spec, imagem_exemplo.parent, 960, 540, 30)


def test_spec_ida_e_volta():
    dados = {"imagem": "x.png", "largura": 100, "altura": 50, "duracao": 3, "camera": "zoom",
             "partes": [{"nome": "sol", "animacao": "girando+pulsar", "caixa": [80, 10, 20, 40]}]}
    spec = SpecCena.de_dict(dados)
    assert spec.camera.movimento == "zoom_in"
    parte = spec.partes[0]
    assert parte.animacoes == ["girar", "pulsar"]
    assert parte.caixa == (20, 10, 80, 40)  # caixa invertida é corrigida
    assert parte.pivo_efetivo() == (50, 25)
    assert SpecCena.de_dict(spec.para_dict()).para_dict() == spec.para_dict()


def test_spec_erros():
    with pytest.raises(ErroSpec):
        Parte.de_dict({"nome": "x", "animacoes": ["explodir"], "caixa": [0, 0, 1, 1]})
    with pytest.raises(ErroSpec):
        Parte.de_dict({"nome": "x", "animacoes": ["girar"], "caixa": [0, 0, 1]})


def test_ajustar_tamanho_reescala_coordenadas():
    spec = SpecCena("x.png", 100, 50, partes=[Parte("a", ["girar"], (10, 10, 20, 20), pivo=(15, 15))])
    spec.ajustar_tamanho(200, 100)
    assert spec.partes[0].caixa == (20, 20, 40, 40)
    assert spec.partes[0].pivo == (30, 30)


def test_recortes_automaticos_do_exemplo(renderizador):
    assert all(modo == "auto" for modo in renderizador.modos_mascara.values())
    partes = {pa.nome: pa for pa in renderizador.partes}
    braco = partes["braço levantado"].mascara
    x0, y0, x1, y1 = partes["braço levantado"].caixa
    # o recorte do braço não pode levar a cabeça junto (fica à direita da caixa, acima do ombro)
    cabeca = braco[y0:int(y0 + 0.6 * (y1 - y0)), int(x0 + 0.75 * (x1 - x0)):x1]
    assert cabeca.mean() < 0.15
    # o sol precisa dos raios, não só do disco
    sol = partes["sol"]
    sx0, sy0, sx1, sy1 = sol.caixa
    faixa_raios = sol.mascara[sy0:sy0 + (sy1 - sy0) // 6, sx0:sx1]
    assert faixa_raios.max() > 0.9


def test_fundo_reconstruido_limpo(renderizador):
    # onde estava a nuvem, o fundo deve voltar a ser o céu liso
    nuvem = next(pa for pa in renderizador.partes if pa.nome == "nuvem")
    x0, y0, x1, y1 = nuvem.caixa
    regiao = renderizador.fundo[y0 + 5:y1 - 5, x0 + 5:x1 - 5].astype(int)
    ceu = renderizador.img[5, 5].astype(int)
    assert np.abs(regiao - ceu).max() <= 6


def test_olhos_piscam_juntos(renderizador):
    olhos = [pa for pa in renderizador.partes if "piscar" in pa.pinturas]
    assert len(olhos) == 2
    assert olhos[0]._dados["piscar"][2] == olhos[1]._dados["piscar"][2]


def test_poses_basicas(imagem_exemplo):
    from animacao2d.animacao.efeitos import ParteAnimada

    img = np.zeros((100, 200, 3), np.uint8)
    girar = ParteAnimada(Parte("g", ["girar"], (10, 10, 50, 50)), img, 1.0, 5.0, 1)
    assert girar.pose(0).identidade()
    assert girar.pose(1.0).angulo == pytest.approx(360 * 0.12)
    aparecer = ParteAnimada(Parte("a", ["aparecer"], (10, 10, 50, 50), atraso=1.0), img, 1.0, 5.0, 1)
    assert aparecer.pose(0.5).alfa == 0.0
    assert aparecer.pose(3.0).sx == pytest.approx(1.0)
    deslizar = ParteAnimada(Parte("d", ["deslizar"], (10, 10, 50, 50), direcao="esquerda"), img, 1.0, 5.0, 1)
    assert deslizar.pose(2.0).dx < 0
    assert isinstance(deslizar.pose(2.0), Pose)


def test_quadros_mudam_e_tem_tamanho_certo(renderizador):
    a = renderizador.quadro(0)
    b = renderizador.quadro(45)
    assert a.shape == (540, 960, 3) and a.dtype == np.uint8
    assert np.abs(a.astype(int) - b.astype(int)).mean() > 1.0


def test_renderiza_mp4(imagem_exemplo, tmp_path):
    spec = SpecCena.carregar(imagem_exemplo.with_suffix(".json"))
    spec.duracao = 1.0
    saida = RenderizadorCena(spec, imagem_exemplo.parent, 640, 360, 30).renderizar(tmp_path / "saida.mp4",
                                                                                      preset="ultrafast")
    quadros, segundos = imageio_ffmpeg.count_frames_and_secs(str(saida))
    assert quadros == 30
    assert segundos == pytest.approx(1.0, abs=0.05)


def test_so_camera_sem_partes(imagem_exemplo):
    spec = SpecCena(str(imagem_exemplo), 1456, 816, duracao=2.0)
    spec.camera.movimento = "pan_direita"
    r = RenderizadorCena(spec, imagem_exemplo.parent, 480, 270, 30)
    assert not r.moveis
    assert not np.array_equal(r.quadro(0), r.quadro(59))
