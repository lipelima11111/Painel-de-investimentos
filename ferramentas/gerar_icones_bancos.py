"""Gera os icones SVG dos bancos e o catalogo `bancos.json`.

Rodar so quando quiser adicionar/alterar um banco pre-cadastrado:

    python ferramentas/gerar_icones_bancos.py

Depois disso, adicionar um banco NOVO ao sistema nao exige mexer em nenhuma
logica: basta acrescentar uma linha em BANCOS (ou desenhar um SVG a mao) e
rodar este script de novo. O runtime (painel/static/js/bancos.js) so le o
`bancos.json` gerado - nao conhece cor, sigla nem regra de desenho.

Os icones sao um selo colorido (cor real de marca + sigla) em vez do logo
oficial: reproduzir a marca registrada de cada instituicao exigiria licenciar
o arquivo oficial de cada uma, e o objetivo aqui - identificar o banco de
relance, com arquivo local, sem chamada de rede - fica igualmente atendido.
"""

from __future__ import annotations

import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTA_ICONES = RAIZ / "painel" / "static" / "img" / "bancos"
ARQUIVO_JSON = RAIZ / "painel" / "static" / "dados" / "bancos.json"

# id, nome de exibicao, sigla do selo, cor de fundo, cor do texto, aliases p/ busca
BANCOS = [
    ("nubank",       "Nubank",                  "NU",  "#820AD1", "#FFFFFF",
     ["nubank", "nu", "nu pagamentos", "nu bank"]),
    ("bb",           "Banco do Brasil",         "BB",  "#FADB00", "#003087",
     ["banco do brasil", "banco brasil", "bb"]),
    ("caixa",        "Caixa Economica Federal", "CEF", "#0070AD", "#FFFFFF",
     ["caixa", "caixa economica", "caixa economica federal", "cef"]),
    ("itau",         "Itau Unibanco",           "ITA", "#EC7000", "#FFFFFF",
     ["itau", "banco itau", "itau unibanco"]),
    ("bradesco",     "Bradesco",                "BRA", "#CC092F", "#FFFFFF",
     ["bradesco", "banco bradesco"]),
    ("santander",    "Santander",               "SAN", "#EC0000", "#FFFFFF",
     ["santander", "banco santander"]),
    ("inter",        "Banco Inter",             "INT", "#FF7A00", "#FFFFFF",
     ["inter", "banco inter"]),
    ("c6",           "C6 Bank",                 "C6",  "#1B1B1B", "#FFFFFF",
     ["c6", "c6 bank", "banco c6"]),
    ("btg",          "BTG Pactual",             "BTG", "#002A5C", "#FFFFFF",
     ["btg", "btg pactual", "banco btg pactual"]),
    ("sicredi",      "Sicredi",                 "SDI", "#4C9C2E", "#FFFFFF",
     ["sicredi"]),
    ("sicoob",       "Sicoob",                  "SIC", "#00AE9D", "#FFFFFF",
     ["sicoob"]),
    ("pagbank",      "PagBank",                 "PAG", "#37C871", "#06331B",
     ["pagbank", "pagseguro", "pag bank", "pag seguro"]),
    ("mercadopago",  "Mercado Pago",            "MP",  "#009EE3", "#FFFFFF",
     ["mercado pago", "mercadopago", "mp"]),
    ("picpay",       "PicPay",                  "PIC", "#11C76F", "#06331B",
     ["picpay", "pic pay"]),
    ("neon",         "Neon",                    "NEO", "#00E7B7", "#053B33",
     ["neon", "banco neon"]),
    ("original",     "Banco Original",          "ORI", "#00B2A9", "#FFFFFF",
     ["original", "banco original"]),
    ("sofisa",       "Sofisa Direto",           "SOF", "#E30613", "#FFFFFF",
     ["sofisa", "sofisa direto", "banco sofisa"]),
    ("banrisul",     "Banrisul",                "BRS", "#004A93", "#FFFFFF",
     ["banrisul", "banco do estado do rio grande do sul"]),
    ("pan",          "Banco Pan",               "PAN", "#F37021", "#FFFFFF",
     ["pan", "banco pan", "panamericano", "banco panamericano"]),
    ("safra",        "Banco Safra",             "SAF", "#00543C", "#FFFFFF",
     ["safra", "banco safra"]),
    ("xp",           "XP Investimentos",        "XP",  "#000000", "#FFFFFF",
     ["xp", "xp investimentos", "xp corretora"]),
    ("will",         "Will Bank",               "WIL", "#6B4EFF", "#FFFFFF",
     ["will", "will bank", "willbank"]),
    ("next",         "Next",                    "NXT", "#00FF5F", "#063312",
     ["next", "next banco", "banco next"]),
    ("agibank",      "Agibank",                 "AGI", "#FF5A00", "#FFFFFF",
     ["agibank", "agi bank"]),
    ("bmg",          "Banco BMG",               "BMG", "#EE7D00", "#FFFFFF",
     ["bmg", "banco bmg"]),
    ("stone",        "Stone",                   "STN", "#00A868", "#FFFFFF",
     ["stone", "stone pagamentos"]),
    ("infinitepay",  "InfinitePay",             "INF", "#00D26A", "#06331B",
     ["infinitepay", "infinite pay"]),
    ("brb",          "BRB - Banco de Brasilia", "BRB", "#0033A0", "#FFFFFF",
     ["brb", "banco de brasilia", "banco regional de brasilia"]),
]

# tamanho de fonte por comprimento da sigla, pra nunca estourar o selo
FONTE_POR_TAMANHO = {2: 16, 3: 12.5, 4: 10}

MODELO_SELO = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">
  <rect width="40" height="40" rx="9" fill="{cor}"/>
  <text x="20" y="{baseline}" text-anchor="middle" font-family="system-ui, -apple-system, 'Segoe UI', sans-serif" font-weight="700" font-size="{fonte}" fill="{texto}">{sigla}</text>
</svg>
"""

# Icone padrao (predio classico com colunas) para instituicoes fora do catalogo.
ICONE_GENERICO = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">
  <rect width="40" height="40" rx="9" fill="#8B8B86"/>
  <g fill="none" stroke="#FFFFFF" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round">
    <path d="M9 17 L20 9 L31 17 Z"/>
    <line x1="9" y1="17" x2="31" y2="17"/>
    <line x1="11.5" y1="19.5" x2="11.5" y2="28"/>
    <line x1="16.5" y1="19.5" x2="16.5" y2="28"/>
    <line x1="23.5" y1="19.5" x2="23.5" y2="28"/>
    <line x1="28.5" y1="19.5" x2="28.5" y2="28"/>
    <line x1="8" y1="30.5" x2="32" y2="30.5"/>
  </g>
</svg>
"""


def gerar() -> None:
    PASTA_ICONES.mkdir(parents=True, exist_ok=True)
    ARQUIVO_JSON.parent.mkdir(parents=True, exist_ok=True)

    catalogo = []
    for id_, nome, sigla, cor, texto, aliases in BANCOS:
        fonte = FONTE_POR_TAMANHO.get(len(sigla), 10)
        svg = MODELO_SELO.format(cor=cor, texto=texto, sigla=sigla, fonte=fonte,
                                 baseline=25 if fonte >= 15 else 24.5)
        (PASTA_ICONES / f"{id_}.svg").write_text(svg, encoding="utf-8")
        catalogo.append({
            "id": id_, "nome": nome,
            "icone": f"img/bancos/{id_}.svg",
            "aliases": aliases,
        })

    (PASTA_ICONES / "outro.svg").write_text(ICONE_GENERICO, encoding="utf-8")
    # Ordem alfabetica so pra deixar o arquivo legivel - quem decide a ordem
    # exibida na lista e o front (locale pt-BR, ver bancos.js).
    catalogo.sort(key=lambda b: b["nome"].casefold())

    dados = {
        "bancos": catalogo,
        "outro": {"id": "outro", "nome": "Outro banco", "icone": "img/bancos/outro.svg"},
    }
    ARQUIVO_JSON.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    print(f"{len(catalogo)} icones gravados em {PASTA_ICONES}")
    print(f"catalogo gravado em {ARQUIVO_JSON}")


if __name__ == "__main__":
    gerar()
