"""Calendario de dias uteis do mercado financeiro brasileiro (padrao ANBIMA).

O mercado de renda fixa brasileiro capitaliza juros em base 252 dias uteis, entao
todo o motor de calculo depende de saber exatamente quais dias sao uteis.
Feriados nacionais bancarios = fixos + moveis derivados da Pascoa.

Contagem em O(1): `dias_uteis_entre` nao percorre mais o intervalo dia a dia.
Cada ano tem uma tabela de somas de prefixos (dias uteis acumulados por dia do
ano) mais o total acumulado desde EPOCA, entao a contagem e uma subtracao.
Isso importa porque o motor pede a contagem centenas de vezes por simulacao.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

DIAS_UTEIS_ANO = 252

# Nao existe serie do BACEN antes disso; abaixo de EPOCA caimos na contagem lenta.
EPOCA = 1990


def pascoa(ano: int) -> date:
    """Domingo de Pascoa pelo algoritmo de Meeus/Jones/Butcher (gregoriano)."""
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    lg = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lg) // 451
    mes, dia = divmod(h + lg - 7 * m + 114, 31)
    return date(ano, mes, dia + 1)


@lru_cache(maxsize=512)
def feriados_do_ano(ano: int) -> frozenset[date]:
    """Feriados nacionais bancarios de um ano."""
    p = pascoa(ano)
    dias = {
        date(ano, 1, 1),            # Confraternizacao Universal
        p - timedelta(days=48),     # Segunda de Carnaval
        p - timedelta(days=47),     # Terca de Carnaval
        p - timedelta(days=2),      # Sexta-feira Santa
        date(ano, 4, 21),           # Tiradentes
        date(ano, 5, 1),            # Dia do Trabalho
        p + timedelta(days=60),     # Corpus Christi
        date(ano, 9, 7),            # Independencia
        date(ano, 10, 12),          # Nossa Senhora Aparecida
        date(ano, 11, 2),           # Finados
        date(ano, 11, 15),          # Proclamacao da Republica
        date(ano, 12, 25),          # Natal
    }
    # Consciencia Negra virou feriado nacional pela Lei 14.759/2023.
    if ano >= 2024:
        dias.add(date(ano, 11, 20))
    return frozenset(dias)


def _eh_util(d: date) -> bool:
    if d.weekday() >= 5:  # sabado/domingo
        return False
    return d not in feriados_do_ano(d.year)


@lru_cache(maxsize=512)
def _prefixos_do_ano(ano: int) -> tuple[int, ...]:
    """Dias uteis acumulados antes de cada dia do ano.

    prefixos[n] = quantos dias uteis existem entre 1/jan e o n-esimo dia do ano,
    exclusive. O ultimo elemento e o total de dias uteis do ano.
    """
    saida = []
    acumulado = 0
    d = date(ano, 1, 1)
    while d.year == ano:
        saida.append(acumulado)
        if _eh_util(d):
            acumulado += 1
        d += timedelta(days=1)
    saida.append(acumulado)
    return tuple(saida)


@lru_cache(maxsize=512)
def dias_uteis_do_ano(ano: int) -> int:
    return _prefixos_do_ano(ano)[-1]


@lru_cache(maxsize=512)
def _acumulado_antes_do_ano(ano: int) -> int:
    """Dias uteis entre 1/jan/EPOCA e 1/jan/ano."""
    if ano <= EPOCA:
        return 0
    return _acumulado_antes_do_ano(ano - 1) + dias_uteis_do_ano(ano - 1)


def _ordinal_util(d: date) -> int:
    """Dias uteis entre 1/jan/EPOCA e `d`, exclusive."""
    return _acumulado_antes_do_ano(d.year) + _prefixos_do_ano(d.year)[d.timetuple().tm_yday - 1]


class Calendario:
    """Consultas de dias uteis. Contagem em O(1) via somas de prefixos."""

    def eh_dia_util(self, d: date) -> bool:
        return _eh_util(d)

    def proximo_dia_util(self, d: date) -> date:
        while not _eh_util(d):
            d += timedelta(days=1)
        return d

    def dia_util_anterior(self, d: date) -> date:
        while not _eh_util(d):
            d -= timedelta(days=1)
        return d

    def dias_uteis_entre(self, inicio: date, fim: date) -> int:
        """Dias uteis no intervalo [inicio, fim) - convencao de renda fixa."""
        if fim <= inicio:
            return 0
        if inicio.year < EPOCA:
            return self._contagem_lenta(inicio, fim)
        return _ordinal_util(fim) - _ordinal_util(inicio)

    @staticmethod
    def _contagem_lenta(inicio: date, fim: date) -> int:
        total, d = 0, inicio
        while d < fim:
            if _eh_util(d):
                total += 1
            d += timedelta(days=1)
        return total

    def iter_dias_uteis(self, inicio: date, fim: date):
        d = inicio
        while d <= fim:
            if _eh_util(d):
                yield d
            d += timedelta(days=1)

    def dias_uteis_do_mes(self, ano: int, mes: int) -> int:
        inicio = date(ano, mes, 1)
        fim = date(ano + (mes == 12), (mes % 12) + 1, 1)
        return self.dias_uteis_entre(inicio, fim)

    def ultimo_dia_util_do_mes(self, ano: int, mes: int) -> date:
        import calendar
        return self.dia_util_anterior(date(ano, mes, calendar.monthrange(ano, mes)[1]))


CALENDARIO = Calendario()
