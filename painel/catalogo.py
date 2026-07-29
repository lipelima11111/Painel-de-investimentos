"""Catalogo de produtos de renda fixa e regras tributarias brasileiras.

As regras que MUDARAM ao longo do tempo ficam em tabelas datadas (custodia da
B3, isencao do Tesouro Selic, regra da poupanca). O motor consulta essas tabelas
pela data do evento, nunca pelo valor vigente hoje - e o que permite simular um
investimento de 2008 com as regras de 2008.
"""

from __future__ import annotations

from datetime import date

# --------------------------------------------------------------- indexadores --
# Cada indexador define o que o campo "taxa" do investimento significa.
INDEXADORES = {
    "POS_CDI": {
        "nome": "Pos-fixado - % do CDI",
        "unidade": "% do CDI",
        "ajuda": "Ex.: 110 = rende 110% do CDI. O mais comum em CDB/LCI/LCA.",
        "padrao": 100.0,
        "maximo": 400.0,
    },
    "CDI_MAIS": {
        "nome": "CDI + spread",
        "unidade": "% a.a. acima do CDI",
        "ajuda": "Ex.: 2 = CDI + 2% ao ano. Comum em debentures.",
        "padrao": 2.0,
        "maximo": 30.0,
    },
    "PRE": {
        "nome": "Prefixado",
        "unidade": "% a.a.",
        "ajuda": "Taxa fixa contratada. Ex.: 13.5 = 13,5% ao ano ate o vencimento.",
        "padrao": 13.5,
        "maximo": 60.0,
    },
    "IPCA_MAIS": {
        "nome": "IPCA + juro real",
        "unidade": "% a.a. + IPCA",
        "ajuda": "Ex.: 6.5 = IPCA + 6,5% ao ano. Protege da inflacao.",
        "padrao": 6.5,
        "maximo": 30.0,
    },
    "SELIC_MAIS": {
        "nome": "Selic + spread",
        "unidade": "% a.a. acima da Selic",
        "ajuda": "Ex.: 0.05 = Selic + 0,05%. Padrao do Tesouro Selic.",
        "padrao": 0.05,
        "maximo": 10.0,
    },
    "POUPANCA": {
        "nome": "Poupanca",
        "unidade": "regra oficial",
        "ajuda": "0,5% a.m. + TR quando a Selic passa de 8,5% a.a.; senao 70% da Selic + TR.",
        "padrao": 0.0,
        "maximo": 0.0,
    },
}

# ------------------------------------------------------------------- produtos --
# isento_ir  : rendimento livre de imposto de renda para pessoa fisica
# fgc        : coberto pelo Fundo Garantidor de Creditos (ate R$ 250 mil por CPF/instituicao)
# custodia   : taxa de custodia da B3 (Tesouro Direto)
# come_cotas : antecipacao semestral de IR (fundos)
TIPOS = {
    "CDB": {
        "nome": "CDB",
        "descricao": "Certificado de Deposito Bancario",
        "isento_ir": False, "fgc": True, "custodia": 0.0, "come_cotas": False,
        "indexadores": ["POS_CDI", "CDI_MAIS", "PRE", "IPCA_MAIS"],
        "grupo": "Bancario",
    },
    "RDB": {
        "nome": "RDB",
        "descricao": "Recibo de Deposito Bancario (sem liquidez antecipada)",
        "isento_ir": False, "fgc": True, "custodia": 0.0, "come_cotas": False,
        "indexadores": ["POS_CDI", "CDI_MAIS", "PRE", "IPCA_MAIS"],
        "grupo": "Bancario",
    },
    "LC": {
        "nome": "LC",
        "descricao": "Letra de Cambio (financeiras)",
        "isento_ir": False, "fgc": True, "custodia": 0.0, "come_cotas": False,
        "indexadores": ["POS_CDI", "CDI_MAIS", "PRE", "IPCA_MAIS"],
        "grupo": "Bancario",
    },
    "LCI": {
        "nome": "LCI",
        "descricao": "Letra de Credito Imobiliario - isenta de IR",
        "isento_ir": True, "fgc": True, "custodia": 0.0, "come_cotas": False,
        "indexadores": ["POS_CDI", "PRE", "IPCA_MAIS"],
        "grupo": "Isento",
    },
    "LCA": {
        "nome": "LCA",
        "descricao": "Letra de Credito do Agronegocio - isenta de IR",
        "isento_ir": True, "fgc": True, "custodia": 0.0, "come_cotas": False,
        "indexadores": ["POS_CDI", "PRE", "IPCA_MAIS"],
        "grupo": "Isento",
    },
    "LIG": {
        "nome": "LIG",
        "descricao": "Letra Imobiliaria Garantida - isenta de IR",
        "isento_ir": True, "fgc": False, "custodia": 0.0, "come_cotas": False,
        "indexadores": ["POS_CDI", "PRE", "IPCA_MAIS"],
        "grupo": "Isento",
    },
    "CRI_CRA": {
        "nome": "CRI / CRA",
        "descricao": "Certificado de Recebiveis - isento de IR, sem FGC",
        "isento_ir": True, "fgc": False, "custodia": 0.0, "come_cotas": False,
        "indexadores": ["POS_CDI", "CDI_MAIS", "PRE", "IPCA_MAIS"],
        "grupo": "Isento",
    },
    "DEBENTURE_INCENTIVADA": {
        "nome": "Debenture incentivada",
        "descricao": "Infraestrutura (Lei 12.431) - isenta de IR",
        "isento_ir": True, "fgc": False, "custodia": 0.0, "come_cotas": False,
        "indexadores": ["CDI_MAIS", "PRE", "IPCA_MAIS"],
        "grupo": "Isento",
    },
    "DEBENTURE": {
        "nome": "Debenture comum",
        "descricao": "Divida corporativa tributada",
        "isento_ir": False, "fgc": False, "custodia": 0.0, "come_cotas": False,
        "indexadores": ["POS_CDI", "CDI_MAIS", "PRE", "IPCA_MAIS"],
        "grupo": "Credito privado",
    },
    "TESOURO_SELIC": {
        "nome": "Tesouro Selic",
        "descricao": "LFT - pos-fixado, liquidez diaria, risco soberano",
        "isento_ir": False, "fgc": False, "custodia": 0.20, "come_cotas": False,
        "indexadores": ["SELIC_MAIS"],
        "grupo": "Tesouro Direto",
    },
    "TESOURO_PREFIXADO": {
        "nome": "Tesouro Prefixado",
        "descricao": "LTN/NTN-F - taxa travada ate o vencimento",
        "isento_ir": False, "fgc": False, "custodia": 0.20, "come_cotas": False,
        "indexadores": ["PRE"],
        "grupo": "Tesouro Direto",
    },
    "TESOURO_IPCA": {
        "nome": "Tesouro IPCA+",
        "descricao": "NTN-B - juro real acima da inflacao",
        "isento_ir": False, "fgc": False, "custodia": 0.20, "come_cotas": False,
        "indexadores": ["IPCA_MAIS"],
        "grupo": "Tesouro Direto",
    },
    "POUPANCA": {
        "nome": "Poupanca",
        "descricao": "Isenta de IR, rende so no aniversario mensal",
        "isento_ir": True, "fgc": True, "custodia": 0.0, "come_cotas": False,
        "indexadores": ["POUPANCA"],
        "grupo": "Isento",
    },
    "FUNDO_DI": {
        "nome": "Fundo DI / Renda Fixa",
        "descricao": "Sofre come-cotas semestral (maio e novembro)",
        "isento_ir": False, "fgc": False, "custodia": 0.0, "come_cotas": True,
        "indexadores": ["POS_CDI", "CDI_MAIS"],
        "grupo": "Fundos",
    },
}

# ---------------------------------------------------------------- tributacao --
# IR regressivo sobre o rendimento (renda fixa), por dias corridos.
TABELA_IR = [
    (180, 22.5),
    (360, 20.0),
    (720, 17.5),
    (10**9, 15.0),
]

# IOF regressivo sobre o rendimento em resgates com menos de 30 dias corridos.
TABELA_IOF = [
    96, 93, 90, 86, 83, 80, 76, 73, 70, 66,
    63, 60, 56, 53, 50, 46, 43, 40, 36, 33,
    30, 26, 23, 20, 16, 13, 10, 6, 3, 0,
]

ALIQUOTA_COME_COTAS = 15.0
TETO_FGC = 250_000.0
ISENCAO_CUSTODIA_TESOURO_SELIC = 10_000.0
CUSTODIA_B3 = 0.20

# A poupanca nao sofre IOF: quem saca antes do aniversario simplesmente perde o
# rendimento do mes. Todos os demais produtos - inclusive os isentos de IR, pois
# o IOF/titulos independe da isencao - entram na tabela regressiva de 30 dias.
ISENTOS_DE_IOF = {"POUPANCA"}

# ------------------------------------------------------- regimes historicos --
# Taxa de custodia da B3 no Tesouro Direto, por inicio de vigencia (% a.a.).
# Fonte: B3/Tesouro Nacional. 0,30% ate 2019; 0,25% a partir de ago/2019;
# 0,20% a partir de jan/2022.
CUSTODIA_B3_HISTORICO = (
    (date(2002, 1, 1), 0.30),
    (date(2019, 8, 1), 0.25),
    (date(2022, 1, 1), 0.20),
)

# A isencao de custodia sobre os primeiros R$ 10 mil em Tesouro Selic so passou
# a valer em agosto de 2020. Antes disso a taxa incidia sobre o saldo inteiro.
INICIO_ISENCAO_TESOURO_SELIC = date(2020, 8, 1)

# Poupanca: a Lei 12.703/2012 (MP 567) criou a "regra nova" para depositos
# feitos a partir de 04/05/2012. Depositos anteriores mantem para sempre a
# regra antiga (0,5% a.m. + TR), independentemente da Selic.
INICIO_POUPANCA_NOVA = date(2012, 5, 4)
LIMITE_SELIC_POUPANCA = 8.5      # % a.a.: acima disso vale 0,5% a.m.
TAXA_BASICA_POUPANCA = 0.5       # % a.m.
FATOR_SELIC_POUPANCA = 0.70      # 70% da meta Selic quando ela fica <= 8,5%

# Cenarios da projecao: choque na Selic/CDI futuros, em pontos percentuais.
CENARIOS = {
    "base": {"nome": "Selic de hoje", "delta_selic": 0.0},
    "queda": {"nome": "Selic -2 p.p.", "delta_selic": -2.0},
    "alta": {"nome": "Selic +2 p.p.", "delta_selic": 2.0},
}


def custodia_b3(d: date) -> float:
    """Taxa de custodia da B3 vigente em `d`, em % a.a."""
    taxa = CUSTODIA_B3_HISTORICO[0][1]
    for inicio, valor in CUSTODIA_B3_HISTORICO:
        if d >= inicio:
            taxa = valor
        else:
            break
    return taxa


def isencao_custodia_vigente(d: date, cota: float) -> float:
    """Parcela isenta de custodia no Tesouro Selic em `d`."""
    return cota if d >= INICIO_ISENCAO_TESOURO_SELIC else 0.0


def taxa_poupanca_regra(selic_meta: float, tr: float, regra_nova: bool) -> float:
    """Rendimento mensal da poupanca em %, pela regra legal.

    Confere com a serie 195 do BACEN nos quatro regimes testados (Selic 2,00 /
    6,50 / 9,25 / 14,75). Dois detalhes que a formula "de bolso" erra:

    * quando a Selic fica <= 8,5%, a base e a MENSALIZACAO de 70% da meta anual,
      `(1 + 0,70 x Selic)^(1/12) - 1`, e nao 70% da Selic mensalizada;
    * a TR COMPOE com a remuneracao basica, nao e somada a ela.
    """
    if regra_nova and selic_meta <= LIMITE_SELIC_POUPANCA:
        basica = (1 + FATOR_SELIC_POUPANCA * selic_meta / 100) ** (1 / 12) - 1
    else:
        basica = TAXA_BASICA_POUPANCA / 100
    return ((1 + basica) * (1 + tr / 100) - 1) * 100


def aliquota_ir(dias_corridos: int) -> float:
    """Aliquota de IR em % para o prazo informado.

    Escrita como comparacoes diretas, e nao como varredura de TABELA_IR: e
    chamada uma vez por lote em cada ponto avaliado da serie, e o laco aparecia
    no perfil de investimentos longos com aporte mensal.
    """
    if dias_corridos <= 180:
        return 22.5
    if dias_corridos <= 360:
        return 20.0
    if dias_corridos <= 720:
        return 17.5
    return 15.0


def aliquota_iof(dias_corridos: int) -> float:
    """Aliquota de IOF em % sobre o rendimento."""
    if dias_corridos >= 30 or dias_corridos < 1:
        return 0.0
    return float(TABELA_IOF[dias_corridos - 1])


def proxima_faixa_ir(dias_corridos: int) -> dict | None:
    """Quantos dias faltam para cair na proxima faixa de IR (mais barata)."""
    for limite, _ in TABELA_IR[:-1]:
        if dias_corridos <= limite:
            proxima = next(a for lim, a in TABELA_IR if lim > limite)
            return {
                "dias_restantes": limite - dias_corridos + 1,
                "aliquota_atual": aliquota_ir(dias_corridos),
                "proxima_aliquota": proxima,
            }
    return None


def catalogo_publico() -> dict:
    """Metadados enviados ao front para montar os formularios."""
    return {
        "tipos": {
            k: {
                "nome": v["nome"],
                "descricao": v["descricao"],
                "isento_ir": v["isento_ir"],
                "fgc": v["fgc"],
                "custodia": v["custodia"],
                "come_cotas": v["come_cotas"],
                "indexadores": v["indexadores"],
                "grupo": v["grupo"],
            }
            for k, v in TIPOS.items()
        },
        "indexadores": INDEXADORES,
        "tabela_ir": [{"ate_dias": l, "aliquota": a} for l, a in TABELA_IR],
        "teto_fgc": TETO_FGC,
        "cenarios": [{"chave": k, **v} for k, v in CENARIOS.items()],
    }
