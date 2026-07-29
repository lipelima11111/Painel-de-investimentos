"""Gera `dados_bacen_congelados.py` a partir das series REAIS do SGS.

Rodar so quando quiser estender a cobertura historica dos testes:

    python testes/gerar_fixture.py

Congelar o recorte (em vez de bater na API dentro do teste) mantem a suite
determinista e offline, sem abrir mao de validar contra numero oficial.
"""

from __future__ import annotations

import json
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

SGS = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{c}/dados?formato=json&dataInicial={i}&dataFinal={f}"

# Meses-teste: um por regime de juros relevante desde 2008.
MESES = [(2008, 6), (2012, 6), (2015, 3), (2018, 9), (2020, 4), (2025, 1)]
# Datas-teste da poupanca: antes e depois da Lei 12.703, Selic alta e baixa.
DATAS_POUPANCA = [
    date(2008, 6, 1), date(2011, 3, 1), date(2012, 6, 1), date(2013, 5, 1),
    date(2015, 3, 1), date(2017, 9, 1), date(2018, 6, 1), date(2020, 6, 1),
    date(2021, 2, 1), date(2023, 4, 1), date(2025, 6, 1),
]


def baixar(codigo: int, inicio: date, fim: date) -> dict[str, float]:
    """Uma janela de uma serie. O SGS devolve 502 sob rajada; insistimos."""
    url = SGS.format(c=codigo, i=inicio.strftime("%d/%m/%Y"), f=fim.strftime("%d/%m/%Y"))
    for tentativa in range(6):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                bruto = json.load(r)
            break
        except Exception as exc:
            if tentativa == 5:
                raise
            print(f"  {codigo}: {exc} - nova tentativa em {2 ** tentativa}s")
            time.sleep(2 ** tentativa)
    time.sleep(0.4)
    saida = {}
    for linha in bruto:
        d, m, a = linha["data"].split("/")
        saida[f"{a}-{m}-{d}"] = float(linha["valor"].replace(",", "."))
    return saida


def proximo_mes(ano: int, mes: int) -> date:
    return date(ano + (mes == 12), mes % 12 + 1, 1)


def main() -> None:
    cdi, selic, cdi_mes, selic_mes = {}, {}, {}, {}
    for ano, mes in MESES:
        ini, fim = date(ano, mes, 1), proximo_mes(ano, mes)
        # Uma semana de folga apos o mes: o motor consulta o proximo dia util
        # depois do fim para estimar o "rendimento do dia", e sem essa folga os
        # testes acusariam lacuna de serie onde o problema e o recorte.
        cdi.update(baixar(12, ini, fim + timedelta(days=7)))
        selic.update(baixar(11, ini, fim + timedelta(days=7)))
        cdi_mes[f"{ano:04d}-{mes:02d}"] = baixar(4391, ini, ini)[f"{ano:04d}-{mes:02d}-01"]
        selic_mes[f"{ano:04d}-{mes:02d}"] = baixar(4390, ini, ini)[f"{ano:04d}-{mes:02d}-01"]

    poup_nova, poup_antiga, tr, meta = {}, {}, {}, {}
    for d in DATAS_POUPANCA:
        poup_nova.update(baixar(195, d, d))
        poup_antiga.update(baixar(25, d, d))
        tr.update(baixar(226, d, d))
        meta.update(baixar(432, d, d))

    # IPCA de um ano inteiro, para validar a convencao de VNA do IPCA+.
    ipca = {k[:7]: v for k, v in baixar(433, date(2018, 1, 1), date(2019, 12, 31)).items()}

    destino = Path(__file__).resolve().parent / "dados_bacen_congelados.py"
    corpo = [
        '"""Recortes REAIS das series do SGS/BACEN, congelados para os testes.',
        "",
        f"Gerado por testes/gerar_fixture.py em {date.today().isoformat()}.",
        "Fonte: https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados",
        "",
        "  12 = CDI % a.d.      4391 = CDI acumulado no mes %",
        "  11 = Selic % a.d.    4390 = Selic acumulada no mes %",
        " 195 = poupanca nova     25 = poupanca antiga",
        " 226 = TR              432 = meta Selic       433 = IPCA mensal",
        '"""',
        "",
    ]
    for nome, valor in [
        ("CDI_DIARIO", cdi), ("SELIC_DIARIA", selic),
        ("CDI_ACUMULADO_MES", cdi_mes), ("SELIC_ACUMULADA_MES", selic_mes),
        ("POUPANCA_NOVA", poup_nova), ("POUPANCA_ANTIGA", poup_antiga),
        ("TR", tr), ("SELIC_META", meta), ("IPCA_MENSAL", ipca),
    ]:
        corpo.append(f"{nome} = {json.dumps(valor, indent=4, sort_keys=True)}")
        corpo.append("")
    destino.write_text("\n".join(corpo), encoding="utf-8")
    print(f"gravado {destino} ({destino.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
