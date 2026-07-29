"""Fidelidade historica: o motor contra as series oficiais do BACEN.

Todo numero esperado aqui saiu do SGS (ver `dados_bacen_congelados.py`, gerado
por `gerar_fixture.py`). A pergunta que estes testes respondem e sempre a mesma:
uma simulacao iniciada em 2008, 2012, 2015, 2018, 2020 ou 2025 reproduz o que
DE FATO aconteceu naquele periodo - ou o motor esta aplicando a taxa de hoje ao
passado?

Rodar com: pytest testes/test_historico.py -v
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dados_bacen_congelados as F
from painel.bacen import DadosMercado
from painel.calculos import Investimento, Motor
from painel.catalogo import custodia_b3, isencao_custodia_vigente, taxa_poupanca_regra

APLICADO = 1_000_000.0     # base grande: erro de centavo nao mascara erro de taxa


def proximo_mes(ano: int, mes: int) -> date:
    return date(ano + (mes == 12), mes % 12 + 1, 1)


@pytest.fixture
def mercado() -> DadosMercado:
    """Mercado com as series historicas REAIS e um "hoje" bem diferente delas.

    A meta Selic de hoje (14,75%) nao se parece com nenhum dos periodos
    testados. Se algum calculo passado vazar para a taxa corrente, os numeros
    estouram - e esse e exatamente o ponto.
    """
    return DadosMercado(
        selic_meta=14.75, cdi_anual=14.65, ipca_12m=4.5, ipca_projetado=4.5,
        selic_projetada=14.0, poupanca_mensal=0.6707, tr_mensal=0.1699,
        atualizado_em="2026-07-27T00:00:00", online=True,
        cdi_diario=F.CDI_DIARIO,
        selic_diaria=F.SELIC_DIARIA,
        ipca_mensal=F.IPCA_MENSAL,
        poupanca_por_data=F.POUPANCA_NOVA,
        poupanca_antiga_por_data=F.POUPANCA_ANTIGA,
        tr_por_data=F.TR,
        selic_meta_degraus=F.SELIC_META,
    )


# ------------------------------------------------------------- CDI e Selic --
@pytest.mark.parametrize("chave", sorted(F.CDI_ACUMULADO_MES))
def test_cdi_do_mes_bate_com_a_serie_4391_do_bacen(mercado, chave):
    """100% do CDI num mes fechado = CDI acumulado publicado pelo BACEN."""
    ano, mes = int(chave[:4]), int(chave[5:])
    inv = Investimento(nome="cdb", tipo="CDB", indexador="POS_CDI", taxa=100.0,
                       valor_aplicado=APLICADO, data_aplicacao=date(ano, mes, 1))
    motor = Motor(mercado)
    r = motor.simular(inv, proximo_mes(ano, mes), com_serie=False)
    rendimento = (r.final.bruto / APLICADO - 1) * 100
    assert round(rendimento, 2) == F.CDI_ACUMULADO_MES[chave]
    assert motor.avisos == []     # 100% do periodo veio da serie oficial


@pytest.mark.parametrize("chave", sorted(F.SELIC_ACUMULADA_MES))
def test_selic_do_mes_bate_com_a_serie_4390_do_bacen(mercado, chave):
    """Tesouro Selic com spread zero = Selic acumulada publicada pelo BACEN."""
    ano, mes = int(chave[:4]), int(chave[5:])
    inv = Investimento(nome="lft", tipo="CDB", indexador="SELIC_MAIS", taxa=0.0,
                       valor_aplicado=APLICADO, data_aplicacao=date(ano, mes, 1))
    motor = Motor(mercado)
    r = motor.simular(inv, proximo_mes(ano, mes), com_serie=False)
    rendimento = (r.final.bruto / APLICADO - 1) * 100
    assert round(rendimento, 2) == F.SELIC_ACUMULADA_MES[chave]


def test_percentual_do_cdi_escala_pela_formula_b3(mercado):
    """110% do CDI nao e (1+TDI)^1,1: e 1 + TDI x 1,1, dia a dia."""
    motor = Motor(mercado)
    inicio, fim = date(2015, 3, 1), date(2015, 4, 1)
    esperado = 1.0
    for dia in sorted(F.CDI_DIARIO):
        if inicio.isoformat() <= dia < fim.isoformat():
            esperado *= 1 + F.CDI_DIARIO[dia] / 100 * 1.10
    inv = Investimento(nome="cdb", tipo="CDB", indexador="POS_CDI", taxa=110.0,
                       valor_aplicado=APLICADO, data_aplicacao=inicio)
    r = motor.simular(inv, fim, com_serie=False)
    assert r.final.bruto == pytest.approx(APLICADO * esperado, abs=0.01)


def test_simulacao_de_2015_nao_usa_a_selic_de_2026(mercado):
    """A regressao-mae: 2015 rendia ~1% a.m.; 2026 renderia bem mais.

    Se o motor usasse a taxa corrente para o passado, marco/2015 renderia perto
    de 1,15%. A serie oficial diz 1,04%.
    """
    inv = Investimento(nome="cdb", tipo="CDB", indexador="POS_CDI", taxa=100.0,
                       valor_aplicado=APLICADO, data_aplicacao=date(2015, 3, 1))
    r = Motor(mercado).simular(inv, date(2015, 4, 1), com_serie=False)
    rendimento = (r.final.bruto / APLICADO - 1) * 100
    assert rendimento == pytest.approx(1.04, abs=0.005)
    taxa_de_hoje = ((1 + 14.65 / 100) ** (22 / 252) - 1) * 100
    assert rendimento < taxa_de_hoje - 0.05


def test_meta_selic_historica_e_usada_quando_falta_a_serie_diaria(mercado):
    """Sem CDI publicado, a reconstrucao usa a meta DA EPOCA, nao a de hoje."""
    motor = Motor(mercado)
    assert motor._selic_meta_em(date(2015, 3, 10)) == 12.25
    assert motor._selic_meta_em(date(2021, 2, 10)) == 2.00
    assert motor._selic_meta_em(date(2020, 6, 10)) == 3.00
    # data futura: projecao do Focus, nao o degrau historico
    assert motor._selic_anual_ref(date(2030, 1, 1)) == pytest.approx(14.0)


def test_lacuna_de_serie_vira_aviso_explicito(mercado):
    """Reconstruir e aceitavel; reconstruir em silencio nao."""
    motor = Motor(mercado)
    inv = Investimento(nome="cdb", tipo="CDB", indexador="POS_CDI", taxa=100.0,
                       valor_aplicado=APLICADO, data_aplicacao=date(2010, 1, 4))
    r = motor.simular(inv, date(2010, 2, 1), com_serie=False)
    assert r.avisos and "2010" in r.avisos[0]


# ------------------------------------------------------------------ poupanca --
@pytest.mark.parametrize("dia", sorted(F.POUPANCA_NOVA))
def test_poupanca_nova_bate_com_a_serie_195(dia):
    """Regra da Lei 12.703 reproduzida a partir da meta Selic e da TR."""
    calculado = taxa_poupanca_regra(F.SELIC_META[dia], F.TR[dia], regra_nova=True)
    assert round(calculado, 4) == pytest.approx(F.POUPANCA_NOVA[dia], abs=0.0001)


@pytest.mark.parametrize("dia", sorted(F.POUPANCA_ANTIGA))
def test_poupanca_antiga_bate_com_a_serie_25(dia):
    """Regra pre-2012: 0,5% a.m. COMPOSTO com a TR, em qualquer nivel de Selic."""
    calculado = taxa_poupanca_regra(F.SELIC_META[dia], F.TR[dia], regra_nova=False)
    assert round(calculado, 4) == pytest.approx(F.POUPANCA_ANTIGA[dia], abs=0.0001)


def test_motor_escolhe_a_serie_da_poupanca_pela_data_do_deposito(mercado):
    """Em jun/2020 a poupanca antiga rendia 0,50% e a nova 0,1733%."""
    motor = Motor(mercado)
    assert motor.taxa_poupanca_mes(date(2020, 6, 1), regra_nova=False) == 0.5
    assert motor.taxa_poupanca_mes(date(2020, 6, 1), regra_nova=True) == 0.1733


def test_poupanca_antiga_rende_bem_mais_no_periodo_de_selic_baixa(mercado):
    """Duas poupancas, mesmo valor, so muda a data do deposito."""
    motor = Motor(mercado)
    comum = dict(nome="p", tipo="POUPANCA", indexador="POUPANCA", taxa=0.0,
                 valor_aplicado=10_000.0)
    antiga = Investimento(**comum, data_aplicacao=date(2012, 5, 3))
    nova = Investimento(**comum, data_aplicacao=date(2012, 5, 4))
    fim = date(2021, 6, 1)
    saldo_antiga = motor.simular(antiga, fim, com_serie=False).final.bruto
    saldo_nova = motor.simular(nova, fim, com_serie=False).final.bruto
    assert saldo_antiga > saldo_nova
    assert antiga.poupanca_regra_nova is False and nova.poupanca_regra_nova is True


# ---------------------------------------------------------------- IPCA / VNA --
def test_vna_fecha_o_ipca_do_mes_exatamente_entre_dois_dias_15(mercado):
    """De 15/m a 15/(m+1) o VNA acumula EXATAMENTE o IPCA do mes m."""
    motor = Motor(mercado)
    for mes in range(1, 12):
        base, prox = date(2018, mes, 15), date(2018, mes + 1, 15)
        fator = motor._indice_ipca(prox) / motor._indice_ipca(base)
        esperado = 1 + F.IPCA_MENSAL[f"2018-{mes:02d}"] / 100
        assert fator == pytest.approx(esperado, rel=1e-12)


def test_ipca_mais_de_15_a_15_paga_a_inflacao_fechada_do_ano(mercado):
    """IPCA+0% de 15/01/2018 a 15/01/2019 = IPCA composto de jan a dez/2018."""
    motor = Motor(mercado)
    esperado = 1.0
    for mes in range(1, 13):
        esperado *= 1 + F.IPCA_MENSAL[f"2018-{mes:02d}"] / 100
    inv = Investimento(nome="ntnb", tipo="TESOURO_IPCA", indexador="IPCA_MAIS",
                       taxa=0.0, valor_aplicado=APLICADO,
                       data_aplicacao=date(2018, 1, 15))
    r = motor.simular(inv, date(2019, 1, 15), com_serie=False)
    # a custodia da B3 e o unico desconto no caminho; o bruto ja vem liquido dela
    bruto_sem_custodia = r.final.bruto + r.final.custodia_paga
    assert bruto_sem_custodia / APLICADO == pytest.approx(esperado, rel=2e-4)


def test_vna_nao_acompanha_o_mes_civil(mercado):
    """A correcao do dia 20 de um mes usa o IPCA daquele mes, nao do anterior."""
    motor = Motor(mercado)
    # jan/2018 (0,29%) e fev/2018 (0,32%) tem inflacao diferente; a virada do
    # indice acontece no dia 15, entao 14 e 16 de fevereiro caem em meses de
    # referencia distintos.
    antes = motor._indice_ipca(date(2018, 2, 14)) / motor._indice_ipca(date(2018, 2, 13))
    depois = motor._indice_ipca(date(2018, 2, 16)) / motor._indice_ipca(date(2018, 2, 15))
    assert antes != pytest.approx(depois, rel=1e-9)


# --------------------------------------------------------------- custodia B3 --
def test_custodia_b3_usa_a_taxa_vigente_na_data():
    assert custodia_b3(date(2015, 6, 1)) == 0.30
    assert custodia_b3(date(2019, 7, 31)) == 0.30
    assert custodia_b3(date(2019, 8, 1)) == 0.25
    assert custodia_b3(date(2021, 12, 31)) == 0.25
    assert custodia_b3(date(2022, 1, 1)) == 0.20
    assert custodia_b3(date(2026, 7, 27)) == 0.20


def test_isencao_do_tesouro_selic_nao_existia_antes_de_agosto_de_2020():
    assert isencao_custodia_vigente(date(2019, 1, 1), 10_000.0) == 0.0
    assert isencao_custodia_vigente(date(2020, 7, 31), 10_000.0) == 0.0
    assert isencao_custodia_vigente(date(2020, 8, 1), 10_000.0) == 10_000.0


def test_tesouro_selic_de_2015_paga_custodia_sobre_o_saldo_inteiro(mercado):
    """R$ 8 mil em 2015 pagavam custodia; hoje estariam isentos."""
    motor = Motor(mercado)
    inv = Investimento(nome="lft", tipo="TESOURO_SELIC", indexador="SELIC_MAIS",
                       taxa=0.0, valor_aplicado=8_000.0,
                       data_aplicacao=date(2015, 3, 1))
    r = motor.simular(inv, date(2015, 4, 1), com_serie=False)
    assert r.final.custodia_paga > 0


# ------------------------------------------------------- coerencia interna --
def test_serie_do_grafico_bate_com_a_tabela_no_ultimo_ponto(mercado):
    """O 'liquido' do grafico e o da posicao tem de ser o MESMO numero."""
    motor = Motor(mercado)
    inv = Investimento(nome="cdb", tipo="CDB", indexador="POS_CDI", taxa=100.0,
                       valor_aplicado=50_000.0, aporte_mensal=1_000.0,
                       data_aplicacao=date(2015, 3, 2))
    fim = date(2015, 3, 31)
    r = motor.simular(inv, fim)
    assert r.serie[-1]["data"] == fim.isoformat()
    assert r.serie[-1]["liquido"] == pytest.approx(r.final.liquido, abs=0.01)
    assert r.serie[-1]["bruto"] == pytest.approx(r.final.bruto, abs=0.01)


def test_resgate_parcial_consome_a_fatia_certa_do_come_cotas(mercado):
    """O credito do come-cotas rateia pelo RENDIMENTO, nao pelo saldo bruto.

    Ratear pelo bruto - que inclui o principal - diluia o credito: o resgate
    pagava IR a mais e deixava para tras um credito maior do que o devido, e as
    duas pontas nunca fechavam com os 15% do come-cotas.
    """
    from painel.calculos import Resgate
    motor = Motor(mercado)
    aplicado = 100_000.0
    fundo = Investimento(nome="f", tipo="FUNDO_DI", indexador="POS_CDI", taxa=100.0,
                         valor_aplicado=aplicado, data_aplicacao=date(2015, 3, 2),
                         resgates=[Resgate(data=date(2018, 9, 20), valor=50_000.0)])
    r = motor.simular(fundo, date(2018, 9, 28), com_serie=False)
    retido = sum(e["ir"] for e in r.eventos if e["tipo"] == "come_cotas")
    resgate = next(e for e in r.eventos if e["tipo"] == "resgate")
    assert retido > 0

    # Com um unico lote, a fracao resgatada do principal e a mesma do bruto -
    # logo o credito consumido tem de ser essa mesma fracao do come-cotas.
    fracao = resgate["principal"] / aplicado
    assert r.hoje.ir_antecipado == pytest.approx(retido * (1 - fracao), rel=1e-6)

    # E a parcela resgatada fecha em exatamente 15% do seu rendimento bruto.
    credito = retido * fracao
    tributo = credito + resgate["ir"]
    assert tributo / (resgate["rendimento"] + credito) == pytest.approx(0.15, rel=1e-6)
