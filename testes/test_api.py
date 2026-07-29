"""Testes da API Flask: validacao, erros, resgates e rateio de custodia.

Rodar com: pytest testes/ -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from painel.api import criar_app


@pytest.fixture
def cliente(tmp_path):
    app = criar_app(tmp_path)
    app.testing = True
    return app.test_client()


def _cria(cliente, **over):
    dados = {
        "nome": "CDB Teste", "tipo": "CDB", "indexador": "POS_CDI", "taxa": 110,
        "valor_aplicado": 10000, "data_aplicacao": "2024-01-02",
    }
    dados.update(over)
    return cliente.post("/api/investimentos", json=dados)


def test_catalogo_e_mercado_respondem(cliente):
    assert cliente.get("/api/catalogo").status_code == 200
    assert cliente.get("/api/mercado").status_code == 200


def test_cria_le_atualiza_remove_investimento(cliente):
    r = _cria(cliente)
    assert r.status_code == 201
    inv_id = r.get_json()["id"]

    r = cliente.get("/api/investimentos")
    assert r.status_code == 200 and len(r.get_json()) == 1

    r = cliente.put(f"/api/investimentos/{inv_id}", json={
        "nome": "CDB Editado", "tipo": "CDB", "indexador": "POS_CDI", "taxa": 105,
        "valor_aplicado": 10000, "data_aplicacao": "2024-01-02",
    })
    assert r.status_code == 200 and r.get_json()["nome"] == "CDB Editado"

    r = cliente.delete(f"/api/investimentos/{inv_id}")
    assert r.status_code == 200
    assert cliente.get("/api/investimentos").get_json() == []


def test_metodo_nao_permitido_devolve_405_nao_500(cliente):
    """Regressao: o handler generico de Exception capturava tambem HTTPException."""
    r = cliente.delete("/api/carteira")
    assert r.status_code == 405
    assert "erro" in r.get_json()


def test_rota_inexistente_da_404_json(cliente):
    r = cliente.get("/api/rota-que-nao-existe")
    assert r.status_code == 404


def test_corpo_nao_json_e_rejeitado(cliente):
    """POST com Content-Type diferente de application/json deve falhar (freia CSRF simples)."""
    r = cliente.post("/api/investimentos", data="{}", content_type="text/plain")
    assert r.status_code == 400


@pytest.mark.parametrize("campo,valor,msg", [
    ("taxa", -5, "menor"),
    ("valor_aplicado", 0, "obrigatorio"),
    ("data_aplicacao", "2099-01-01", "futuro"),
])
def test_validacao_rejeita_valores_invalidos(cliente, campo, valor, msg):
    r = _cria(cliente, **{campo: valor})
    assert r.status_code == 400


def test_taxa_acima_do_maximo_do_indexador_e_rejeitada(cliente):
    r = _cria(cliente, indexador="POS_CDI", taxa=99999)
    assert r.status_code == 400


def test_indexador_incompativel_com_tipo_e_rejeitado(cliente):
    r = _cria(cliente, tipo="TESOURO_SELIC", indexador="PRE")
    assert r.status_code == 400


def test_resgate_parcial_e_removivel(cliente):
    inv_id = _cria(cliente).get_json()["id"]
    r = cliente.post(f"/api/investimentos/{inv_id}/resgates",
                     json={"data": "2024-06-02", "valor": 1000})
    assert r.status_code == 201
    resgate_id = r.get_json()["resgates"][0]["id"]

    r = cliente.delete(f"/api/investimentos/{inv_id}/resgates/{resgate_id}")
    assert r.status_code == 200
    assert r.get_json()["resgates"] == []


def test_resgate_no_futuro_e_rejeitado(cliente):
    inv_id = _cria(cliente).get_json()["id"]
    r = cliente.post(f"/api/investimentos/{inv_id}/resgates",
                     json={"data": "2099-01-01", "valor": 100})
    assert r.status_code == 400


def test_isencao_de_custodia_e_rateada_entre_titulos_selic(cliente):
    _cria(cliente, tipo="TESOURO_SELIC", indexador="SELIC_MAIS", taxa=0.05,
         valor_aplicado=60000, nome="Selic A")
    _cria(cliente, tipo="TESOURO_SELIC", indexador="SELIC_MAIS", taxa=0.05,
         valor_aplicado=20000, nome="Selic B")
    lista = cliente.get("/api/investimentos").get_json()
    isencoes = {l["nome"]: l["isencao_custodia"] for l in lista}
    assert isencoes["Selic A"] == pytest.approx(7500.0)
    assert isencoes["Selic B"] == pytest.approx(2500.0)
    assert sum(isencoes.values()) == pytest.approx(10000.0)


def test_cenario_invalido_na_projecao_e_rejeitado(cliente):
    _cria(cliente)
    r = cliente.get("/api/carteira/evolucao?anos=5&cenario=inexistente")
    assert r.status_code == 400


def test_carteira_traz_metricas_de_xirr(cliente):
    _cria(cliente)
    r = cliente.get("/api/carteira")
    assert r.status_code == 200
    assert "metricas" in r.get_json()


def test_simulador_ordena_por_liquido_e_marca_o_melhor(cliente):
    r = cliente.post("/api/simulador", json={
        "valor_aplicado": 10000, "prazo_meses": 12,
        "cenarios": [
            {"tipo": "CDB", "indexador": "POS_CDI", "taxa": 110},
            {"tipo": "LCI", "indexador": "POS_CDI", "taxa": 95},
        ],
    })
    assert r.status_code == 200
    resultados = r.get_json()["resultados"]
    assert resultados[0]["diferenca_para_melhor"] == 0
    assert resultados[1]["diferenca_para_melhor"] <= 0
