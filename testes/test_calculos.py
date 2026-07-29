"""Testes do calendario de dias uteis e do motor de calculo.

Rodar com: pytest testes/ -v
"""

from __future__ import annotations

import random
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from painel.bacen import DadosMercado
from painel.calculos import Investimento, Motor, Resgate, consolidar, xirr
from painel.catalogo import aliquota_ir, aliquota_iof
from painel.feriados import CALENDARIO, Calendario


# --------------------------------------------------------------- feriados --
def test_calendario_bate_com_contagem_lenta():
    """A contagem O(1) precisa ser identica a contagem dia a dia original."""
    random.seed(1)
    base = date(1995, 1, 1)
    for _ in range(300):
        a = base + timedelta(days=random.randint(0, 15000))
        b = a + timedelta(days=random.randint(0, 3000))
        assert CALENDARIO.dias_uteis_entre(a, b) == Calendario._contagem_lenta(a, b)


def test_carnaval_e_feriado_movel():
    # Carnaval de 2024: terca-feira 13/02/2024
    assert not CALENDARIO.eh_dia_util(date(2024, 2, 13))
    assert not CALENDARIO.eh_dia_util(date(2024, 2, 12))


def test_consciencia_negra_so_a_partir_de_2024():
    assert CALENDARIO.eh_dia_util(date(2023, 11, 20))
    assert not CALENDARIO.eh_dia_util(date(2024, 11, 20))


def test_fim_de_semana_nunca_e_util():
    assert not CALENDARIO.eh_dia_util(date(2026, 7, 25))  # sabado
    assert not CALENDARIO.eh_dia_util(date(2026, 7, 26))  # domingo


# ------------------------------------------------------------------ mercado --
@pytest.fixture
def mercado_simples() -> DadosMercado:
    """Mercado sem series historicas: tudo cai na regra/projecao constante."""
    return DadosMercado(
        selic_meta=10.0, cdi_anual=9.9, ipca_12m=4.0, ipca_projetado=4.0,
        selic_projetada=10.0, poupanca_mensal=0.6203, tr_mensal=0.0,
        atualizado_em="2026-01-01T00:00:00", online=True,
    )


@pytest.fixture
def motor_simples(mercado_simples) -> Motor:
    return Motor(mercado_simples)


# -------------------------------------------------------- invariantes chave --
def test_prefixado_252_dias_uteis_bate_a_taxa_contratada(motor_simples):
    """Prefixado de 12% a.a. por exatamente 252 dias uteis deve render 12%."""
    inicio = date(2024, 1, 2)
    fim, contados = inicio, 0
    while contados < 252:
        if CALENDARIO.eh_dia_util(fim):
            contados += 1
        fim += timedelta(days=1)
    inv = Investimento(nome="pre", tipo="CDB", indexador="PRE", taxa=12.0,
                        valor_aplicado=1000.0, data_aplicacao=inicio)
    r = motor_simples.simular(inv, fim, com_serie=False)
    assert r.final.bruto == pytest.approx(1120.0, abs=1e-6)
    assert r.final.dias_uteis == 252


def test_percentual_cdi_usa_formula_b3_nao_potencia():
    """100% do CDI deve bater com o acumulado direto da serie, formula B3."""
    serie = {}
    d = date(2025, 1, 2)
    while d < date(2025, 4, 1):
        if CALENDARIO.eh_dia_util(d):
            serie[d.isoformat()] = 0.04  # 0,04% a.d.
        d += timedelta(days=1)
    m = DadosMercado(selic_meta=10.0, cdi_anual=10.0, ipca_12m=4.0, ipca_projetado=4.0,
                      selic_projetada=10.0, poupanca_mensal=0.6, tr_mensal=0.0,
                      atualizado_em="x", online=True, cdi_diario=serie)
    mot = Motor(m)
    inicio, fim = date(2025, 1, 2), date(2025, 4, 1)
    inv = Investimento(nome="cdi", tipo="CDB", indexador="POS_CDI", taxa=100.0,
                        valor_aplicado=1000.0, data_aplicacao=inicio)
    r = mot.simular(inv, fim, com_serie=False)

    fator_direto = 1.0
    for k, v in serie.items():
        if inicio.isoformat() <= k < fim.isoformat():
            fator_direto *= 1 + v / 100
    # Posicao arredonda para centavos; a tolerancia cobre so esse arredondamento.
    assert r.final.bruto == pytest.approx(1000 * fator_direto, abs=0.01)


def test_tabela_ir_regressiva():
    assert aliquota_ir(180) == 22.5
    assert aliquota_ir(181) == 20.0
    assert aliquota_ir(360) == 20.0
    assert aliquota_ir(361) == 17.5
    assert aliquota_ir(720) == 17.5
    assert aliquota_ir(721) == 15.0


def test_tabela_iof_zera_no_dia_30():
    assert aliquota_iof(1) == 96.0
    assert aliquota_iof(29) == 3.0
    assert aliquota_iof(30) == 0.0
    assert aliquota_iof(31) == 0.0


def test_isentos_de_ir_nao_pagam_imposto(motor_simples):
    inv = Investimento(nome="lci", tipo="LCI", indexador="POS_CDI", taxa=100.0,
                        valor_aplicado=10000.0, data_aplicacao=date.today() - timedelta(days=800))
    r = motor_simples.simular(inv, date.today(), com_serie=False)
    assert r.hoje.ir == 0.0
    assert r.hoje.liquido == r.hoje.bruto


# ------------------------------------------------------- poupanca historica --
def test_poupanca_usa_taxa_do_mes_quando_publicada():
    """A regressao original usava a Selic/TR de HOJE para todo o historico.

    Aqui simulamos dois meses com regras opostas (Selic alta e baixa) e
    conferimos que cada mes aplica a SUA PROPRIA taxa publicada, nao a atual.
    """
    m = DadosMercado(
        selic_meta=14.0, cdi_anual=14.0, ipca_12m=4.0, ipca_projetado=4.0,
        selic_projetada=14.0, poupanca_mensal=0.99, tr_mensal=0.1,
        atualizado_em="x", online=True,
        poupanca_por_mes={"2020-01": 0.15, "2022-01": 0.85},
    )
    mot = Motor(m)
    assert mot.taxa_poupanca_mes(date(2020, 1, 15)) == 0.15
    assert mot.taxa_poupanca_mes(date(2022, 1, 15)) == 0.85
    # mes sem dado publicado (futuro) cai na regra legal; a TR COMPOE, nao soma
    assert mot.taxa_poupanca_mes(date(2030, 1, 1)) == pytest.approx(
        ((1.005 * 1.001) - 1) * 100)


def test_poupanca_regra_oficial_selic_baixa_e_alta():
    m_baixa = DadosMercado(selic_meta=8.0, cdi_anual=8.0, ipca_12m=3.0,
                          ipca_projetado=3.0, selic_projetada=8.0,
                          poupanca_mensal=0.0, tr_mensal=0.1,
                          atualizado_em="x", online=True)
    m_alta = DadosMercado(selic_meta=12.0, cdi_anual=12.0, ipca_12m=5.0,
                         ipca_projetado=5.0, selic_projetada=12.0,
                         poupanca_mensal=0.0, tr_mensal=0.1,
                         atualizado_em="x", online=True)
    baixa = Motor(m_baixa).taxa_poupanca_mes(date(2030, 1, 1))
    alta = Motor(m_alta).taxa_poupanca_mes(date(2030, 1, 1))
    assert alta == pytest.approx(((1.005 * 1.001) - 1) * 100)
    # Selic <= 8,5%: a base e a MENSALIZACAO de 70% da meta ANUAL, e nao 70% da
    # Selic ja mensalizada. As duas diferem ~0,7% do rendimento (ver
    # test_poupanca_bate_com_a_serie_oficial_do_bacen).
    basica = (1 + 0.70 * 8.0 / 100) ** (1 / 12)
    assert baixa == pytest.approx((basica * 1.001 - 1) * 100)


def test_poupanca_regra_antiga_vale_para_deposito_pre_2012():
    """Deposito ate 03/05/2012 mantem 0,5% + TR para sempre, mesmo com Selic baixa."""
    m = DadosMercado(selic_meta=2.0, cdi_anual=2.0, ipca_12m=4.0, ipca_projetado=4.0,
                     selic_projetada=2.0, poupanca_mensal=0.1, tr_mensal=0.0,
                     atualizado_em="x", online=True)
    mot = Motor(m)
    antiga = mot.taxa_poupanca_mes(date(2030, 1, 1), regra_nova=False)
    nova = mot.taxa_poupanca_mes(date(2030, 1, 1), regra_nova=True)
    assert antiga == pytest.approx(0.5)
    assert nova == pytest.approx(((1 + 0.70 * 0.02) ** (1 / 12) - 1) * 100)
    assert antiga > 2 * nova    # foi exatamente o que ocorreu entre 2017 e 2021


def test_investimento_escolhe_a_regra_da_poupanca_pela_data_de_aplicacao():
    antigo = Investimento(nome="p", tipo="POUPANCA", indexador="POUPANCA", taxa=0.0,
                          valor_aplicado=1000.0, data_aplicacao=date(2012, 5, 3))
    novo = Investimento(nome="p", tipo="POUPANCA", indexador="POUPANCA", taxa=0.0,
                        valor_aplicado=1000.0, data_aplicacao=date(2012, 5, 4))
    assert not antigo.poupanca_regra_nova
    assert novo.poupanca_regra_nova


def test_poupanca_deposito_no_dia_31_tem_data_base_no_dia_primeiro():
    """Regra do CMN: depositos em 29, 30 e 31 rendem no dia 1o do mes seguinte."""
    assert Motor._data_base_poupanca(date(2020, 1, 31)) == date(2020, 2, 1)
    assert Motor._data_base_poupanca(date(2020, 12, 30)) == date(2021, 1, 1)
    assert Motor._data_base_poupanca(date(2020, 1, 15)) == date(2020, 1, 15)


# -------------------------------------------------------------- performance --
def test_projecao_de_30_anos_e_rapida(motor_simples):
    """Guarda contra regressao de performance: 10 investimentos, 30 anos, <1s."""
    import time
    invs = [
        Investimento(nome=f"i{i}", tipo="CDB", indexador="PRE", taxa=12.0,
                     valor_aplicado=1000.0, aporte_mensal=100.0,
                     data_aplicacao=date(2020, 1, 2))
        for i in range(10)
    ]
    fim = date.today().replace(year=date.today().year + 30)
    t0 = time.perf_counter()
    for inv in invs:
        motor_simples.simular(inv, fim)
    assert time.perf_counter() - t0 < 1.0


# ------------------------------------------------------------------ resgates --
def test_resgate_parcial_reduz_saldo_e_gera_evento(motor_simples):
    inv = Investimento(nome="t", tipo="CDB", indexador="PRE", taxa=12.0,
                        valor_aplicado=10000.0, data_aplicacao=date(2023, 1, 2),
                        resgates=[Resgate(data=date(2024, 1, 2), valor=3000.0)])
    r = motor_simples.simular(inv, date.today(), com_serie=False)
    assert r.hoje.resgatado_bruto == pytest.approx(3000.0)
    assert r.hoje.resgatado_liquido < 3000.0    # IR foi descontado
    assert len(r.eventos) == 1 and r.eventos[0]["tipo"] == "resgate"
    assert not r.encerrado


def test_resgate_total_encerra_a_posicao(motor_simples):
    inv = Investimento(nome="t", tipo="CDB", indexador="PRE", taxa=12.0,
                        valor_aplicado=10000.0, data_aplicacao=date(2023, 1, 2),
                        resgates=[Resgate(data=date(2024, 6, 2), valor=None)])
    r = motor_simples.simular(inv, date.today(), com_serie=False)
    assert r.encerrado
    assert r.hoje.liquido == 0.0
    assert r.hoje.rendimento_liquido > 0    # o ganho ficou registrado no resgate


def test_resgate_nao_pode_ser_maior_que_o_saldo(motor_simples):
    """Pedir mais do que existe deve resgatar o saldo inteiro, sem erro nem saldo negativo."""
    inv = Investimento(nome="t", tipo="CDB", indexador="PRE", taxa=12.0,
                        valor_aplicado=1000.0, data_aplicacao=date(2023, 1, 2),
                        resgates=[Resgate(data=date(2024, 1, 2), valor=999_999.0)])
    r = motor_simples.simular(inv, date.today(), com_serie=False)
    assert r.hoje.liquido == 0.0
    assert r.encerrado


# ---------------------------------------------------------------- come-cotas --
def test_come_cotas_credita_ir_proporcional_ao_rendimento_do_lote(motor_simples):
    """O IR final nunca deve ficar fora da faixa [15%, 22.5%] do rendimento."""
    inv = Investimento(nome="fundo", tipo="FUNDO_DI", indexador="POS_CDI", taxa=100.0,
                        valor_aplicado=5000.0, aporte_mensal=1000.0,
                        data_aplicacao=date(2023, 1, 10))
    r = motor_simples.simular(inv, date.today(), com_serie=False)
    p = r.hoje
    rendimento = p.bruto - p.aportado + p.ir_antecipado
    imposto = p.ir + p.ir_antecipado
    assert rendimento > 0
    aliquota_efetiva = 100 * imposto / rendimento
    assert 15.0 - 1e-6 <= aliquota_efetiva <= 22.5 + 1e-6


# --------------------------------------------------------------------- xirr --
def test_xirr_de_um_unico_deposito_e_a_taxa_anualizada():
    """1000 vira 1210 em exatos 2 anos -> XIRR de 10% a.a."""
    fluxos = [(date(2022, 1, 1), -1000.0), (date(2024, 1, 1), 1210.0)]
    assert xirr(fluxos) == pytest.approx(10.0, abs=0.05)


def test_xirr_sem_sinal_trocado_e_none():
    assert xirr([(date(2024, 1, 1), -1000.0)]) is None
    assert xirr([(date(2024, 1, 1), -1000.0), (date(2024, 6, 1), -500.0)]) is None


# ------------------------------------------------------------------- carteira --
def test_consolidar_soma_campos_e_calcula_rentabilidade(motor_simples):
    inv1 = Investimento(nome="a", tipo="CDB", indexador="PRE", taxa=12.0,
                        valor_aplicado=1000.0, data_aplicacao=date(2023, 1, 2))
    inv2 = Investimento(nome="b", tipo="LCI", indexador="PRE", taxa=10.0,
                        valor_aplicado=2000.0, data_aplicacao=date(2023, 1, 2))
    r1 = motor_simples.simular(inv1, date.today(), com_serie=False)
    r2 = motor_simples.simular(inv2, date.today(), com_serie=False)
    total = consolidar([r1.hoje, r2.hoje])
    assert total["aportado"] == pytest.approx(3000.0)
    assert total["quantidade"] == 2
    assert total["liquido"] == pytest.approx(r1.hoje.liquido + r2.hoje.liquido)
