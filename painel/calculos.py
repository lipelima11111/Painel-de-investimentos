"""Motor de calculo de renda fixa.

Convencoes seguidas:

* Capitalizacao em base 252 dias uteis (padrao do mercado brasileiro).
* "% do CDI" usa a formula B3/CETIP: fator = 1 + TDI x (p/100), onde TDI e a
  taxa DI diaria. Nao e (1+TDI)^p.
* Spreads (CDI+, Selic+, IPCA+, prefixado) capitalizam como (1 + i)^(1/252).
* IR e IOF sao calculados lote a lote - cada aporte tem seu proprio prazo e,
  portanto, sua propria aliquota. Em fundos com come-cotas o imposto ja retido
  entra como credito, distribuido entre os lotes pelo rendimento de cada um.
* Resgates (totais ou parciais) consomem os lotes em FIFO e realizam IR/IOF na
  data do resgate.

Fidelidade historica - a regra que manda em todo o resto:

* NENHUM calculo sobre o passado usa a taxa de hoje. O CDI e a Selic vem das
  series diarias do BACEN (12 e 11); a meta Selic vem dos degraus do Copom
  (432); a TR vem da 226. So o FUTURO usa o Focus, deslocado pelo cenario.
* Quando falta publicacao para um dia util ja ocorrido, o trecho e reconstruido
  pela meta Selic VIGENTE NAQUELA DATA e o motor registra um aviso em
  `Motor.avisos` - reconstruir e aceitavel, reconstruir em silencio nao.
* Poupanca tem duas regras vivas e uma serie do BACEN para cada: depositos ate
  03/05/2012 seguem a antiga (0,5% a.m. composto com a TR, serie 25) para
  sempre; a partir de 04/05/2012 vale a Lei 12.703 (serie 195). Entre 2017 e
  2021 a antiga rendeu mais que o dobro da nova.
* IPCA+ segue a convencao de VNA da ANBIMA: o indice vira no dia 15 de cada
  mes e o IPCA do mes m e acumulado pro-rata em dias uteis entre 15/m e
  15/(m+1). A defasagem e de meio mes e nao coincide com o mes civil.
* Taxa de custodia da B3 e isencao do Tesouro Selic sao tabelas datadas (ver
  `catalogo.py`): 0,30% / 0,25% / 0,20% conforme a epoca, e a isencao dos
  primeiros R$ 10 mil so existe a partir de ago/2020.

Limitacao conhecida: titulos sao avaliados pela CURVA DO PAPEL (carrego ate o
vencimento), sem marcacao a mercado. Para Tesouro Selic e pos-fixados em geral
isso equivale a realidade; para Tesouro Prefixado e IPCA+ resgatados ANTES do
vencimento o preco real oscila com a curva de juros, e reproduzir isso exigiria
a serie de precos diarios do Tesouro Transparente.

Um "indice" acumulado (produtorio dos fatores diarios) permite avaliar
qualquer lote em O(1): valor = principal x indice_hoje / indice_do_aporte.
A contagem de dias uteis tambem e O(1) (ver `feriados.py`), e o laco carrega o
proprio contador - avaliar a serie nao recontagem o calendario.
"""

from __future__ import annotations

import calendar
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import date, timedelta

from .bacen import DadosMercado
from .catalogo import (
    ALIQUOTA_COME_COTAS,
    INICIO_POUPANCA_NOVA,
    ISENCAO_CUSTODIA_TESOURO_SELIC,
    ISENTOS_DE_IOF,
    TIPOS,
    aliquota_iof,
    aliquota_ir,
    custodia_b3,
    isencao_custodia_vigente,
    proxima_faixa_ir,
    taxa_poupanca_regra,
)
from .feriados import CALENDARIO, DIAS_UTEIS_ANO

MAX_PONTOS_SERIE = 420


# ------------------------------------------------------------------- modelos --
@dataclass
class Resgate:
    data: date
    valor: float | None = None      # None = resgate total (encerra a posicao)
    id: int | None = None

    @classmethod
    def de_linha(cls, linha: dict) -> "Resgate":
        v = linha.get("valor")
        return cls(
            id=linha.get("id"),
            data=date.fromisoformat(linha["data"]),
            valor=None if v in (None, "", 0) else float(v),
        )


@dataclass
class Investimento:
    nome: str
    tipo: str
    indexador: str
    taxa: float
    valor_aplicado: float
    data_aplicacao: date
    id: int | None = None
    aporte_mensal: float = 0.0
    data_vencimento: date | None = None
    instituicao: str = ""
    observacoes: str = ""
    resgates: list[Resgate] = field(default_factory=list)
    # Parcela da isencao de custodia do Tesouro Selic atribuida a esta posicao.
    # A isencao e de R$ 10 mil por CONTA, nao por titulo: quem tem duas posicoes
    # divide o beneficio. Quem tem uma so recebe o valor inteiro.
    isencao_custodia: float = ISENCAO_CUSTODIA_TESOURO_SELIC

    @classmethod
    def de_linha(cls, linha: dict) -> "Investimento":
        return cls(
            id=linha.get("id"),
            nome=linha["nome"],
            tipo=linha["tipo"],
            indexador=linha["indexador"],
            taxa=float(linha["taxa"]),
            valor_aplicado=float(linha["valor_aplicado"]),
            aporte_mensal=float(linha.get("aporte_mensal") or 0),
            data_aplicacao=date.fromisoformat(linha["data_aplicacao"]),
            data_vencimento=(
                date.fromisoformat(linha["data_vencimento"])
                if linha.get("data_vencimento") else None
            ),
            instituicao=linha.get("instituicao", "") or "",
            observacoes=linha.get("observacoes", "") or "",
            resgates=[Resgate.de_linha(r) for r in (linha.get("resgates") or [])],
        )

    @property
    def meta(self) -> dict:
        return TIPOS[self.tipo]

    @property
    def poupanca_regra_nova(self) -> bool:
        """Depositos ate 03/05/2012 seguem a regra antiga da poupanca para sempre."""
        return self.data_aplicacao >= INICIO_POUPANCA_NOVA


@dataclass
class Contexto:
    """Estado acumulado da simulacao (o que nao cabe no indice)."""

    aportado: float = 0.0            # tudo que ja entrou
    ir_pago: float = 0.0             # come-cotas retido e ainda nao compensado
    custo_base: float = 0.0          # base do come-cotas
    custodia_paga: float = 0.0
    resgatado_bruto: float = 0.0
    resgatado_liquido: float = 0.0
    ir_realizado: float = 0.0
    iof_realizado: float = 0.0
    dias_uteis: int = 0
    fechado: bool = False            # resgate total encerrou a posicao
    eventos: list[dict] = field(default_factory=list)   # come-cotas e resgates


@dataclass
class Posicao:
    """Fotografia do investimento em uma data."""

    data: date
    dias_corridos: int
    dias_uteis: int
    aportado: float           # tudo que ja foi aportado
    principal: float          # base ainda investida (aportado - principal resgatado)
    bruto: float              # saldo de mercado antes de impostos
    rendimento_bruto: float   # rendimento tributavel do saldo remanescente
    ir: float                 # IR se resgatar tudo hoje
    ir_antecipado: float      # come-cotas ja retido
    iof: float
    ir_realizado: float       # IR ja pago em resgates
    iof_realizado: float
    custodia_paga: float
    resgatado_bruto: float
    resgatado_liquido: float
    liquido: float            # o que cai na conta se resgatar o saldo agora
    rendimento_liquido: float  # ganho total: (liquido + resgatado) - aportado
    aliquota_ir_efetiva: float
    rendimento_dia: float     # quanto rende no proximo dia util
    rentabilidade_bruta: float   # % sobre o aportado
    rentabilidade_liquida: float

    def dict(self) -> dict:
        d = self.__dict__.copy()
        d["data"] = self.data.isoformat()
        return d


@dataclass
class Resultado:
    investimento: Investimento
    hoje: Posicao
    final: Posicao
    serie: list[dict] = field(default_factory=list)
    encerrado: bool = False   # ja passou do vencimento ou foi resgatado por inteiro
    marcos: dict[str, Posicao] = field(default_factory=dict)  # data ISO -> posicao
    fluxos: list[tuple[date, float]] = field(default_factory=list)
    eventos: list[dict] = field(default_factory=list)
    taxa_anualizada: float | None = None   # % a.a. (XIRR do fluxo de caixa)
    cdi_periodo: float | None = None       # % a.a. do CDI no mesmo intervalo
    pct_cdi: float | None = None           # taxa_anualizada / cdi_periodo
    # Trechos em que alguma taxa passada nao veio da serie oficial do BACEN.
    avisos: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------- XIRR --
def xirr(fluxos: list[tuple[date, float]]) -> float | None:
    """Taxa interna de retorno anual de um fluxo datado, em %.

    Newton com queda para bissecao. Devolve None quando nao ha sinal trocado
    (ex.: nada resgatado ainda e saldo zero) ou o fluxo e degenerado.
    """
    if len(fluxos) < 2:
        return None
    if not (any(v < 0 for _, v in fluxos) and any(v > 0 for _, v in fluxos)):
        return None
    t0 = min(d for d, _ in fluxos)
    prazos = [((d - t0).days / 365.0, v) for d, v in fluxos]
    if max(t for t, _ in prazos) <= 0:
        return None

    def vpl(taxa: float) -> float:
        return sum(v / (1 + taxa) ** t for t, v in prazos)

    taxa = 0.1
    for _ in range(80):
        f = vpl(taxa)
        derivada = sum(-t * v / (1 + taxa) ** (t + 1) for t, v in prazos)
        if abs(derivada) < 1e-12:
            break
        nova = taxa - f / derivada
        if nova <= -0.9999:
            nova = (taxa - 0.9999) / 2
        if abs(nova - taxa) < 1e-10:
            return nova * 100
        taxa = nova
    # bissecao: mais lenta, mas nao escapa
    baixo, alto = -0.9999, 10.0
    if vpl(baixo) * vpl(alto) > 0:
        return None
    for _ in range(200):
        meio = (baixo + alto) / 2
        if vpl(baixo) * vpl(meio) <= 0:
            alto = meio
        else:
            baixo = meio
    return (baixo + alto) / 2 * 100


class Motor:
    """Avalia investimentos dia a dia.

    `delta_selic` desloca em pontos percentuais a Selic/CDI esperados para o
    FUTURO (cenarios de projecao). O passado nunca e alterado.
    """

    def __init__(self, mercado: DadosMercado, delta_selic: float = 0.0):
        self.m = mercado
        self.delta = delta_selic
        self.cal = CALENDARIO
        self.hoje = date.today()
        self._cdi_acumulado: tuple[dict, list, float] | None = None
        self._metas = sorted(mercado.selic_meta_degraus)
        self._vna: dict[tuple[int, int], float] = {}
        self._vna_dia: dict[date, float] = {}
        self.avisos: list[str] = []

    # ------------------------------------------------------------- avisos --
    def _aviso(self, texto: str) -> None:
        if texto not in self.avisos:
            self.avisos.append(texto)

    def _lacuna(self, rotulo: str, serie: str, d: date) -> None:
        """Marca que uma taxa JA OCORRIDA teve de ser reconstruida.

        Reconstruir e melhor do que aplicar a taxa de hoje ao passado, mas o
        usuario precisa saber que aquele trecho nao veio da serie oficial.

        A ponta da serie e caso a parte: o BACEN so publica o CDI de hoje amanha,
        entao os ultimos dias uteis SEMPRE faltam. Avisar sobre isso todo dia
        treinaria o usuario a ignorar o aviso justamente quando ele importa.
        """
        fim = (self.m.cobertura.get(serie) or (None, None))[1]
        if fim is not None and d.isoformat() > fim:
            if self.cal.dias_uteis_entre(date.fromisoformat(fim), d) <= 5:
                return
            self._aviso(f"{rotulo}: a serie oficial do BACEN termina em {fim}. "
                        "O periodo seguinte foi projetado, nao observado.")
            return
        self._aviso(f"{rotulo}: sem publicacao oficial do BACEN em {d.year}. "
                    "O trecho foi reconstruido pela meta Selic vigente na epoca.")

    # ------------------------------------------------------- taxas diarias --
    def _selic_meta_em(self, d: date) -> float:
        """Meta Selic vigente em `d`, pelos degraus de decisao do Copom."""
        if not self._metas:
            return self.m.selic_meta
        i = bisect_right(self._metas, d.isoformat())
        if i == 0:
            # Antes do primeiro registro: o mais antigo conhecido ainda e uma
            # referencia muito melhor do que a meta de hoje.
            return self.m.selic_meta_degraus[self._metas[0]]
        return self.m.selic_meta_degraus[self._metas[i - 1]]

    def _selic_anual_ref(self, d: date | None) -> float:
        """Selic anual de referencia.

        Passado e presente: a meta VIGENTE NAQUELA DATA. Futuro: a projecao do
        Focus, deslocada pelo cenario de choque. Usar a meta de hoje para
        remunerar 2015 era a maior fonte de erro historico do motor.
        """
        if d is None:
            return self.m.selic_meta
        if d > self.hoje:
            return max(0.0, self.m.selic_projetada + self.delta)
        return self._selic_meta_em(d)

    def _cdi_anual_ref(self, d: date | None) -> float:
        """CDI anual de referencia, preservando o spread historico contra a Selic."""
        if d is None:
            return self.m.cdi_anual
        spread = self.m.cdi_anual - self.m.selic_meta
        return max(0.0, self._selic_anual_ref(d) + spread)

    def _tdi(self, d: date) -> float:
        """Taxa DI do dia, em decimal - a serie 12 do BACEN quando ela existe."""
        v = self.m.cdi_diario.get(d.isoformat())
        if v is not None:
            return v / 100
        if d <= self.hoje and self.cal.eh_dia_util(d):
            self._lacuna("CDI", "cdi_diario", d)
        return (1 + self._cdi_anual_ref(d) / 100) ** (1 / DIAS_UTEIS_ANO) - 1

    def _selic_dia(self, d: date) -> float:
        v = self.m.selic_diaria.get(d.isoformat())
        if v is not None:
            return v / 100
        if d <= self.hoje and self.cal.eh_dia_util(d):
            self._lacuna("Selic", "selic_diaria", d)
        return (1 + self._selic_anual_ref(d) / 100) ** (1 / DIAS_UTEIS_ANO) - 1

    # ----------------------------------------------------------- IPCA / VNA --
    def _ipca_mes(self, ref: tuple[int, int]) -> float:
        """IPCA do mes de referencia em %. Sem publicacao, projecao do Focus."""
        v = self.m.ipca_mensal.get(f"{ref[0]:04d}-{ref[1]:02d}")
        if v is None:
            return ((1 + self.m.ipca_projetado / 100) ** (1 / 12) - 1) * 100
        return v

    def _ancora_ipca(self) -> tuple[int, int]:
        if not self.m.ipca_mensal:
            return (self.hoje.year, self.hoje.month)
        a, m = min(self.m.ipca_mensal).split("-")
        return (int(a), int(m))

    def _fator_vna_mes(self, ref: tuple[int, int]) -> float:
        """Fator acumulado do IPCA no dia 15 do mes `ref`.

        No dia 15 do mes m, o VNA ja incorporou o IPCA fechado ate o mes m-1.
        A ancora e arbitraria: o motor so usa RAZOES entre dois VNAs.
        """
        if ref in self._vna:
            return self._vna[ref]
        ancora = self._ancora_ipca()
        if ref <= ancora:
            if ref < ancora:
                # Antes do IPCA baixado nao ha correcao a aplicar - e isso
                # SUBESTIMA o titulo. Nunca deve acontecer (o cliente busca 400
                # dias antes do investimento mais antigo), mas se acontecer o
                # usuario tem de ver, nao adivinhar.
                self._aviso(
                    f"IPCA: a serie baixada comeca em {ancora[0]}-{ancora[1]:02d}. "
                    "O periodo anterior ficou sem correcao pela inflacao.")
            self._vna[ref] = 1.0
            return 1.0
        cursor = ancora
        self._vna[ancora] = 1.0
        while cursor < ref:
            prox = (cursor[0] + 1, 1) if cursor[1] == 12 else (cursor[0], cursor[1] + 1)
            self._vna[prox] = self._vna[cursor] * (1 + self._ipca_mes(cursor) / 100)
            cursor = prox
        return self._vna[ref]

    def _indice_ipca(self, d: date) -> float:
        """VNA do IPCA na data `d`, na convencao ANBIMA / Tesouro Nacional.

        O indice de referencia vira no dia 15 de cada mes: entre o dia 15 do mes
        m e o dia 15 do mes m+1 o titulo acumula o IPCA do mes m, pro-rata em
        DIAS UTEIS. Por isso uma NTN-B que vence em 15/08 paga exatamente a
        inflacao fechada ate julho - a defasagem e de meio mes, nao de um mes,
        e nao coincide com o mes civil.
        """
        cache = self._vna_dia.get(d)
        if cache is not None:
            return cache
        ref = ((d.year, d.month) if d.day >= 15 else
               ((d.year - 1, 12) if d.month == 1 else (d.year, d.month - 1)))
        base = date(ref[0], ref[1], 15)
        prox = date(ref[0] + 1, 1, 15) if ref[1] == 12 else date(ref[0], ref[1] + 1, 15)
        total = self.cal.dias_uteis_entre(base, prox)
        valor = self._fator_vna_mes(ref)
        if total > 0:
            decorridos = self.cal.dias_uteis_entre(base, d)
            valor *= (1 + self._ipca_mes(ref) / 100) ** (decorridos / total)
        self._vna_dia[d] = valor
        return valor

    def _fator_ipca_dia(self, d: date) -> float:
        """Correcao do VNA pelo dia util `d`, creditada no dia seguinte."""
        anterior = self._indice_ipca(d)
        return self._indice_ipca(d + timedelta(days=1)) / anterior if anterior else 1.0

    # ------------------------------------------------------- TR e poupanca --
    def _tr_mes(self, d: date | None) -> float:
        if d is not None:
            v = self.m.tr_por_data.get(d.isoformat())
            if v is None:
                v = self.m.tr_por_mes.get(d.isoformat()[:7])
            if v is not None:
                return v
            if d <= self.hoje:
                self._lacuna("TR", "tr", d)
        return self.m.tr_mensal

    def taxa_poupanca_mes(self, d: date | None = None, regra_nova: bool = True) -> float:
        """Rendimento creditado no aniversario `d` da poupanca, em %.

        Duas regras convivem ate hoje, e o BACEN publica uma serie para cada:
        depositos ate 03/05/2012 seguem a regra antiga - 0,5% a.m. composto com
        a TR, serie 25 - para sempre; depositos a partir de 04/05/2012 seguem a
        Lei 12.703, serie 195. Elas so coincidem enquanto a Selic passa de 8,5%:
        entre out/2017 e ago/2021 a poupanca antiga rendeu mais que o dobro da
        nova, e usar uma no lugar da outra distorce o historico inteiro.
        """
        usa_nova = regra_nova and (d is None or d >= INICIO_POUPANCA_NOVA)
        if d is not None:
            por_data = (self.m.poupanca_por_data if usa_nova
                        else self.m.poupanca_antiga_por_data)
            por_mes = (self.m.poupanca_por_mes if usa_nova
                       else self.m.poupanca_antiga_por_mes)
            v = por_data.get(d.isoformat())
            if v is None:
                v = por_mes.get(d.isoformat()[:7])
            if v is not None:
                return v
            if d <= self.hoje:
                self._lacuna("Poupanca", "poupanca_nova" if usa_nova else "poupanca_antiga", d)
        # Sem publicacao (futuro, ou fora do alcance baixado): regra legal.
        return taxa_poupanca_regra(self._selic_anual_ref(d), self._tr_mes(d), usa_nova)

    def fator_dia(self, inv: Investimento, d: date) -> float:
        ix = inv.indexador
        if ix == "POS_CDI":
            return 1 + self._tdi(d) * inv.taxa / 100
        if ix == "CDI_MAIS":
            return (1 + self._tdi(d)) * (1 + inv.taxa / 100) ** (1 / DIAS_UTEIS_ANO)
        if ix == "PRE":
            return (1 + inv.taxa / 100) ** (1 / DIAS_UTEIS_ANO)
        if ix == "SELIC_MAIS":
            return (1 + self._selic_dia(d)) * (1 + inv.taxa / 100) ** (1 / DIAS_UTEIS_ANO)
        if ix == "IPCA_MAIS":
            return self._fator_ipca_dia(d) * (1 + inv.taxa / 100) ** (1 / DIAS_UTEIS_ANO)
        return 1.0

    def taxa_anual_equivalente(self, inv: Investimento) -> float:
        """Taxa nominal aproximada em % a.a., para comparar produtos."""
        if inv.indexador == "POUPANCA":
            taxa = self.taxa_poupanca_mes(self.hoje, inv.poupanca_regra_nova)
            return ((1 + taxa / 100) ** 12 - 1) * 100
        f = self.fator_dia(inv, self.cal.dia_util_anterior(self.hoje))
        return (f ** DIAS_UTEIS_ANO - 1) * 100

    # ------------------------------------------------------ CDI de referencia --
    def _cdi_map(self) -> tuple[dict, list, float]:
        if self._cdi_acumulado is None:
            datas = sorted(self.m.cdi_diario)
            indice: dict[str, float] = {}
            acumulado = 1.0
            for k in datas:
                indice[k] = acumulado          # fator ANTES do dia k
                acumulado *= 1 + self.m.cdi_diario[k] / 100
            self._cdi_acumulado = (indice, datas, acumulado)
        return self._cdi_acumulado

    def _indice_cdi(self, d: date) -> float:
        """Fator acumulado do CDI desde o inicio da serie ate `d`, exclusive."""
        indice, datas, final = self._cdi_map()
        if not datas:
            return 1.0
        iso = d.isoformat()
        # Aplicar num sabado nao e lacuna: o CDI nao e publicado no fim de
        # semana e o acumulado a partir da segunda ja esta completo. So ha
        # buraco de verdade se algum DIA UTIL ficou de fora - ai o comparativo
        # "% do CDI" mediria menos periodo do que o investimento viveu.
        if iso < datas[0] and self.cal.dias_uteis_entre(d, date.fromisoformat(datas[0])):
            self._aviso("Comparacao com o CDI: a serie baixada comeca em "
                        f"{datas[0]}, depois do inicio do investimento. O % do "
                        "CDI cobre apenas o periodo com dados oficiais.")
        i = bisect_left(datas, iso)
        if i < len(datas):
            return indice[datas[i]]
        ultimo = date.fromisoformat(datas[-1]) + timedelta(days=1)
        du = self.cal.dias_uteis_entre(ultimo, d)
        if du <= 0:
            return final
        return final * (1 + self._tdi(d)) ** du

    def fator_cdi(self, inicio: date, fim: date) -> float:
        """Fator do CDI no intervalo [inicio, fim)."""
        if fim <= inicio:
            return 1.0
        base = self._indice_cdi(inicio)
        return self._indice_cdi(fim) / base if base else 1.0

    def cdi_anualizado(self, inicio: date, fim: date) -> float | None:
        du = self.cal.dias_uteis_entre(inicio, fim)
        if du <= 0:
            return None
        return (self.fator_cdi(inicio, fim) ** (DIAS_UTEIS_ANO / du) - 1) * 100

    # ------------------------------------------------------------ avaliacao --
    def _custodia_ratio(self, inv: Investimento, d: date, bruto: float) -> float:
        """Fator de desconto diario da taxa de custodia da B3, com a taxa da epoca.

        A taxa nao e uma constante: 0,30% a.a. ate 2019, 0,25% de ago/2019 a
        dez/2021 e 0,20% desde jan/2022. A isencao dos primeiros R$ 10 mil em
        Tesouro Selic so existe a partir de ago/2020 - aplicar a isencao de hoje
        a uma posicao de 2015 inventa um beneficio que nao existia.
        """
        if not inv.meta["custodia"] or bruto <= 0:
            return 1.0
        base = bruto
        if inv.tipo == "TESOURO_SELIC":
            base = max(0.0, bruto - isencao_custodia_vigente(d, inv.isencao_custodia))
        if base <= 0:
            return 1.0
        custo = base * ((1 + custodia_b3(d) / 100) ** (1 / DIAS_UTEIS_ANO) - 1)
        return max(0.0, 1 - custo / bruto)

    def _impostos_do_saldo(self, inv: Investimento, d: date, indice: float,
                           lotes: list, ir_pago: float) -> tuple[float, float]:
        """IR e IOF que incidiriam ao resgatar todo o saldo em `d`, lote a lote.

        O come-cotas ja retido (`ir_pago`) entra como credito, rateado entre os
        lotes pelo rendimento de cada um - por isso um unico caminho de codigo
        serve tanto para renda fixa comum quanto para fundos.

        IR e IOF sao independentes: o IOF/titulos incide sobre o rendimento de
        resgates com menos de 30 dias mesmo em papel isento de IR (LCI, LCA,
        CRI/CRA, debenture incentivada). So a poupanca escapa dos dois.
        """
        isento_ir = inv.meta["isento_ir"]
        isento_iof = inv.tipo in ISENTOS_DE_IOF
        if (isento_ir and isento_iof) or not lotes:
            return 0.0, 0.0

        # Caminho rapido: sem come-cotas retido nao ha credito a ratear, entao
        # uma unica passada resolve. E o caso de TODA a renda fixa que nao e
        # fundo, e este laco roda uma vez por lote em cada ponto da serie.
        if not ir_pago:
            ir = iof = 0.0
            for data_lote, valor_lote, indice_lote in lotes:
                rend = valor_lote * (indice / indice_lote - 1)
                if rend <= 0:
                    continue
                dias = (d - data_lote).days
                if not isento_iof and dias < 30:
                    iof_lote = rend * aliquota_iof(dias) / 100
                    iof += iof_lote
                    rend -= iof_lote
                if not isento_ir:
                    ir += rend * aliquota_ir(dias) / 100
            return ir, iof

        rendimentos = []
        for data_lote, valor_lote, indice_lote in lotes:
            rend = valor_lote * indice / indice_lote - valor_lote
            if rend > 0:
                rendimentos.append((data_lote, rend))
        soma = sum(r for _, r in rendimentos)
        if soma <= 0:
            return 0.0, 0.0
        ir = iof = 0.0
        for data_lote, rend in rendimentos:
            credito = ir_pago * (rend / soma)
            base = rend + credito          # rendimento antes do come-cotas
            dias = (d - data_lote).days
            iof_lote = 0.0 if isento_iof else base * aliquota_iof(dias) / 100
            iof += iof_lote
            if not isento_ir:
                ir_lote = (base - iof_lote) * aliquota_ir(dias) / 100
                ir += max(0.0, ir_lote - credito)
        return ir, iof

    def _avaliar(self, inv: Investimento, d: date, indice: float,
                 lotes: list, ctx: Contexto) -> Posicao:
        principal = sum(l[1] for l in lotes)
        bruto = sum(l[1] * indice / l[2] for l in lotes)
        # Em fundos o saldo ja vem liquido do come-cotas retido no caminho; o
        # rendimento bruto "de verdade" soma esse imposto de volta.
        rend_tributavel = bruto - principal + ctx.ir_pago
        ir, iof = self._impostos_do_saldo(inv, d, indice, lotes, ctx.ir_pago)

        liquido = bruto - ir - iof
        if inv.indexador == "POUPANCA":
            # A poupanca so credita no aniversario; mostramos a media diaria.
            taxa = self.taxa_poupanca_mes(d, inv.poupanca_regra_nova)
            rend_dia = bruto * (taxa / 100) / 30
        else:
            base = d if self.cal.eh_dia_util(d) else self.cal.proximo_dia_util(d)
            rend_dia = bruto * (self.fator_dia(inv, base) - 1)
        if (inv.data_vencimento and d >= inv.data_vencimento) or ctx.fechado:
            rend_dia = 0.0

        imposto_total = ir + iof + ctx.ir_pago + ctx.ir_realizado + ctx.iof_realizado
        rendimento_total = (liquido + ctx.resgatado_liquido) - ctx.aportado
        bruto_total = rend_tributavel + (ctx.resgatado_bruto - (ctx.aportado - principal))
        return Posicao(
            data=d,
            dias_corridos=(d - inv.data_aplicacao).days,
            dias_uteis=ctx.dias_uteis,
            aportado=round(ctx.aportado, 2),
            principal=round(principal, 2),
            bruto=round(bruto, 2),
            rendimento_bruto=round(bruto_total, 2),
            ir=round(ir, 2),
            ir_antecipado=round(ctx.ir_pago, 2),
            iof=round(iof, 2),
            ir_realizado=round(ctx.ir_realizado, 2),
            iof_realizado=round(ctx.iof_realizado, 2),
            custodia_paga=round(ctx.custodia_paga, 2),
            resgatado_bruto=round(ctx.resgatado_bruto, 2),
            resgatado_liquido=round(ctx.resgatado_liquido, 2),
            liquido=round(liquido, 2),
            rendimento_liquido=round(rendimento_total, 2),
            aliquota_ir_efetiva=(round(100 * imposto_total / bruto_total, 2)
                                 if bruto_total > 0 else 0.0),
            rendimento_dia=round(rend_dia, 2),
            rentabilidade_bruta=(round(100 * bruto_total / ctx.aportado, 2)
                                 if ctx.aportado else 0.0),
            rentabilidade_liquida=(round(100 * rendimento_total / ctx.aportado, 2)
                                   if ctx.aportado else 0.0),
        )

    # --------------------------------------------------------------- eventos --
    @staticmethod
    def _eh_aniversario(d: date, origem: date) -> bool:
        """Mesmo dia do mes da aplicacao, ajustado para meses curtos."""
        ultimo = calendar.monthrange(d.year, d.month)[1]
        return d.day == min(origem.day, ultimo)

    @staticmethod
    def _data_base_poupanca(origem: date) -> date:
        """Data-base da poupanca.

        Depositos feitos em 29, 30 e 31 tem data-base no dia 1o do mes seguinte
        (regra do CMN) - o mes de fevereiro nao pode simplesmente encurtar o
        aniversario. Um deposito de 31/01 so recebe o primeiro credito em 01/03.
        """
        if origem.day < 29:
            return origem
        return date(origem.year + (origem.month == 12), origem.month % 12 + 1, 1)

    def _executar_resgate(self, inv: Investimento, d: date, indice: float,
                          lotes: list, ctx: Contexto, pedido: float | None) -> None:
        """Consome os lotes em FIFO e realiza IR/IOF na data do resgate."""
        bruto_total = sum(l[1] * indice / l[2] for l in lotes)
        if bruto_total <= 0:
            if pedido is None:
                ctx.fechado = True
            return
        alvo = bruto_total if pedido is None else min(pedido, bruto_total)
        isento_ir = inv.meta["isento_ir"]
        isento_iof = inv.tipo in ISENTOS_DE_IOF
        ir_pago_inicial = ctx.ir_pago
        # O come-cotas ja retido e um credito da CARTEIRA: cada parcela resgatada
        # leva a fatia proporcional ao SEU RENDIMENTO dentro do rendimento total
        # - nao dentro do saldo bruto, que inclui o principal e portanto diluiria
        # o credito, sobretaxando todo resgate de fundo.
        rend_total = sum(max(0.0, l[1] * indice / l[2] - l[1]) for l in lotes)

        restante, ir, iof, principal_saido = alvo, 0.0, 0.0, 0.0
        novos: list[list] = []
        for lote in lotes:
            data_lote, principal_lote, indice_lote = lote
            bruto_lote = principal_lote * indice / indice_lote
            if restante <= 1e-9 or bruto_lote <= 0:
                novos.append(lote)
                continue
            usar = min(bruto_lote, restante)
            fracao = usar / bruto_lote
            principal_usado = principal_lote * fracao
            rend = usar - principal_usado
            if rend > 0 and not (isento_ir and isento_iof):
                credito = (min(ir_pago_inicial * rend / rend_total, ctx.ir_pago)
                           if ir_pago_inicial and rend_total > 0 else 0.0)
                base = rend + credito
                dias = (d - data_lote).days
                iof_lote = 0.0 if isento_iof else base * aliquota_iof(dias) / 100
                iof += iof_lote
                if not isento_ir:
                    ir += max(0.0, (base - iof_lote) * aliquota_ir(dias) / 100 - credito)
                    ctx.ir_pago -= credito
            restante -= usar
            principal_saido += principal_usado
            if bruto_lote - usar > 1e-9:
                novos.append([data_lote, principal_lote - principal_usado, indice_lote])
        lotes[:] = novos

        liquido = alvo - ir - iof
        ctx.resgatado_bruto += alvo
        ctx.resgatado_liquido += liquido
        ctx.ir_realizado += ir
        ctx.iof_realizado += iof
        ctx.custo_base = max(0.0, ctx.custo_base - principal_saido)
        ctx.eventos.append({
            "data": d.isoformat(), "tipo": "resgate",
            "bruto": round(alvo, 2), "liquido": round(liquido, 2),
            "ir": round(ir, 2), "iof": round(iof, 2),
            "principal": round(principal_saido, 2),
            "rendimento": round(alvo - principal_saido, 2),
        })
        if pedido is None or not lotes:
            ctx.fechado = True

    # ----------------------------------------------------------------- motor --
    def simular(self, inv: Investimento, data_fim: date, com_serie: bool = True,
                marcos: list[date] | None = None) -> Resultado:
        """Percorre o investimento dia a dia ate `data_fim`.

        `marcos` pede a posicao completa em datas especificas - assim varias
        projecoes saem de uma unica passada, em vez de uma simulacao por data.
        """
        hoje = self.hoje
        alvos = set(marcos or ())
        capturados: dict[str, Posicao] = {}
        inicio = inv.data_aplicacao
        limite = inv.data_vencimento or data_fim
        fim_calculo = max(min(data_fim, limite), inicio)

        base_poupanca = self._data_base_poupanca(inicio)
        regra_nova = inv.poupanca_regra_nova

        indice = 1.0
        lotes: list[list] = [[inicio, inv.valor_aplicado, 1.0]]
        ctx = Contexto(aportado=inv.valor_aplicado, custo_base=inv.valor_aplicado)
        fluxos: list[tuple[date, float]] = [(inicio, -inv.valor_aplicado)]
        resgates = sorted((r for r in inv.resgates if r.data >= inicio),
                          key=lambda r: (r.data, r.valor is None))
        pendentes = {}
        for r in resgates:
            pendentes.setdefault(r.data, []).append(r)

        total_dias = max(1, (fim_calculo - inicio).days)
        passo = max(1, total_dias // MAX_PONTOS_SERIE)
        serie: list[dict] = []
        pos_hoje: Posicao | None = None

        def registrar(d: date) -> None:
            # Mesmo calculo lote a lote de `_avaliar`: cada aporte tem sua
            # propria idade e, portanto, sua propria aliquota. A versao anterior
            # usava uma unica aliquota, a do aporte mais antigo, e o "liquido"
            # do grafico nao fechava com o da tabela em nenhum investimento com
            # aporte mensal.
            principal = bruto = 0.0
            for _, valor_lote, indice_lote in lotes:
                principal += valor_lote
                bruto += valor_lote * indice / indice_lote
            ir, iof = self._impostos_do_saldo(inv, d, indice, lotes, ctx.ir_pago)
            serie.append({
                "data": d.isoformat(),
                "base": round(principal, 2),
                "bruto": round(bruto, 2),
                "liquido": round(bruto - ir - iof, 2),
                "resgatado": round(ctx.resgatado_liquido, 2),
            })

        # resgate marcado exatamente na data de aplicacao
        if inicio in pendentes:
            for r in pendentes.pop(inicio):
                self._executar_resgate(inv, inicio, indice, lotes, ctx, r.valor)
                fluxos.append((inicio, ctx.eventos[-1]["liquido"]))

        if com_serie:
            registrar(inicio)
        if inicio >= hoje:
            pos_hoje = self._avaliar(inv, inicio, indice, lotes, ctx)

        d = inicio
        contador = 0
        while d < fim_calculo and not ctx.fechado:
            # A renda fixa remunera os dias uteis do intervalo [aplicacao, resgate):
            # o dia da aplicacao conta, o do resgate nao. Por isso o rendimento
            # creditado ao chegar em `d` e o do dia anterior.
            anterior = d
            d += timedelta(days=1)
            contador += 1
            if self.cal.eh_dia_util(anterior):
                ctx.dias_uteis += 1

            # 1) rendimento do dia
            if inv.indexador == "POUPANCA":
                if d.day == base_poupanca.day and d > base_poupanca:
                    indice *= 1 + self.taxa_poupanca_mes(d, regra_nova) / 100
            elif self.cal.eh_dia_util(anterior):
                indice *= self.fator_dia(inv, anterior)
                if inv.meta["custodia"]:
                    bruto = sum(l[1] * indice / l[2] for l in lotes)
                    ratio = self._custodia_ratio(inv, anterior, bruto)
                    ctx.custodia_paga += bruto * (1 - ratio)
                    indice *= ratio

            # 2) come-cotas: ultimo dia util de maio e novembro
            if inv.meta["come_cotas"] and d.month in (5, 11):
                if d == self.cal.ultimo_dia_util_do_mes(d.year, d.month):
                    bruto = sum(l[1] * indice / l[2] for l in lotes)
                    rend = bruto - ctx.custo_base
                    if rend > 0 and bruto > 0:
                        imposto = rend * ALIQUOTA_COME_COTAS / 100
                        ctx.ir_pago += imposto
                        indice *= max(0.0, 1 - imposto / bruto)
                        ctx.custo_base = bruto - imposto
                        ctx.eventos.append({
                            "data": d.isoformat(), "tipo": "come_cotas",
                            "ir": round(imposto, 2), "iof": 0.0,
                            "rendimento": round(rend, 2),
                        })

            # 3) aporte mensal no aniversario da aplicacao
            if inv.aporte_mensal > 0 and self._eh_aniversario(d, inicio):
                lotes.append([d, inv.aporte_mensal, indice])
                ctx.aportado += inv.aporte_mensal
                ctx.custo_base += inv.aporte_mensal
                fluxos.append((d, -inv.aporte_mensal))

            # 4) resgates cadastrados
            if d in pendentes:
                for r in pendentes[d]:
                    self._executar_resgate(inv, d, indice, lotes, ctx, r.valor)
                    fluxos.append((d, ctx.eventos[-1]["liquido"]))

            if d == hoje:
                pos_hoje = self._avaliar(inv, d, indice, lotes, ctx)
            if d in alvos:
                capturados[d.isoformat()] = self._avaliar(inv, d, indice, lotes, ctx)
            if com_serie and (contador % passo == 0 or d == fim_calculo or d == hoje
                              or ctx.fechado):
                registrar(d)

        final = self._avaliar(inv, d if ctx.fechado else fim_calculo,
                              indice, lotes, ctx)
        # Marcos alem do vencimento/encerramento: o valor congela.
        for alvo in alvos:
            capturados.setdefault(alvo.isoformat(), final)
        if pos_hoje is None:
            # Nao passamos por "hoje" no laco: ou o titulo ja venceu/encerrou, ou
            # a simulacao termina antes de hoje. Nos dois casos vale a final.
            pos_hoje = final

        r = Resultado(
            investimento=inv,
            hoje=pos_hoje,
            final=final,
            serie=serie,
            encerrado=bool(ctx.fechado
                           or (inv.data_vencimento and inv.data_vencimento <= hoje)),
            marcos=capturados,
            fluxos=fluxos,
            eventos=list(ctx.eventos),
            avisos=list(self.avisos),
        )
        self._medir(r)
        return r

    def _medir(self, r: Resultado) -> None:
        """Taxa anualizada (XIRR) e comparacao com o CDI do mesmo periodo."""
        p = r.hoje
        fluxos = [f for f in r.fluxos if f[0] <= p.data]
        if p.liquido > 0:
            fluxos = fluxos + [(p.data, p.liquido)]
        taxa = xirr(fluxos)
        r.taxa_anualizada = round(taxa, 2) if taxa is not None else None
        cdi = self.cdi_anualizado(r.investimento.data_aplicacao, p.data)
        r.cdi_periodo = round(cdi, 2) if cdi is not None else None
        if taxa is not None and cdi is not None and cdi > 0:
            r.pct_cdi = round(taxa / cdi * 100, 1)

    # -------------------------------------------------------- conveniencias --
    def posicao_hoje(self, inv: Investimento) -> Posicao:
        return self.avaliar_hoje(inv).hoje

    def avaliar_hoje(self, inv: Investimento) -> Resultado:
        alvo = max(self.hoje, inv.data_aplicacao)
        if inv.data_vencimento:
            alvo = min(alvo, inv.data_vencimento)
        return self.simular(inv, alvo, com_serie=False)

    def detalhes(self, inv: Investimento, r: Resultado | None = None) -> dict:
        """Bloco informativo por investimento (IR, FGC, vencimento, taxa)."""
        dias = (self.hoje - inv.data_aplicacao).days
        meta = inv.meta
        info = {
            "isento_ir": meta["isento_ir"],
            "fgc": meta["fgc"],
            "custodia": meta["custodia"],
            "come_cotas": meta["come_cotas"],
            "taxa_anual_equivalente": round(self.taxa_anual_equivalente(inv), 2),
            "proxima_faixa_ir": None if meta["isento_ir"] else proxima_faixa_ir(dias),
        }
        if r is not None:
            info["taxa_anualizada"] = r.taxa_anualizada
            info["cdi_periodo"] = r.cdi_periodo
            info["pct_cdi"] = r.pct_cdi
            info["encerrado"] = r.encerrado
            info["avisos"] = r.avisos
        if inv.indexador == "POUPANCA":
            info["poupanca_regra"] = "nova" if inv.poupanca_regra_nova else "antiga"
        if meta["custodia"]:
            info["custodia_atual"] = custodia_b3(self.hoje)
        if inv.data_vencimento:
            info["dias_para_vencer"] = (inv.data_vencimento - self.hoje).days
            info["dias_uteis_para_vencer"] = self.cal.dias_uteis_entre(
                self.hoje, inv.data_vencimento)
        return info


# ----------------------------------------------------------------- carteira --
CAMPOS_SOMA = [
    "aportado", "principal", "bruto", "rendimento_bruto", "ir", "ir_antecipado",
    "iof", "ir_realizado", "iof_realizado", "custodia_paga", "resgatado_bruto",
    "resgatado_liquido", "liquido", "rendimento_liquido", "rendimento_dia",
]


def consolidar(posicoes: list[Posicao]) -> dict:
    """Soma um conjunto de posicoes (todas na mesma data) numa visao de carteira."""
    total = {c: 0.0 for c in CAMPOS_SOMA}
    for p in posicoes:
        for c in CAMPOS_SOMA:
            total[c] += getattr(p, c)
    total = {c: round(v, 2) for c, v in total.items()}
    ap = total["aportado"]
    total["impostos_e_taxas"] = round(
        total["ir"] + total["iof"] + total["ir_antecipado"]
        + total["ir_realizado"] + total["iof_realizado"] + total["custodia_paga"], 2)
    total["rentabilidade_liquida"] = round(100 * total["rendimento_liquido"] / ap, 2) if ap else 0.0
    total["rentabilidade_bruta"] = round(100 * total["rendimento_bruto"] / ap, 2) if ap else 0.0
    # Projecao do rendimento corrente: juros COMPOSTOS sobre o saldo bruto, nao
    # o rendimento de um dia multiplicado por 21 ou 252. Na Selic de dois digitos
    # a diferenca no ano passa de 7% do proprio rendimento.
    bruto = total["bruto"]
    if bruto > 0 and total["rendimento_dia"] > 0:
        fator = 1 + total["rendimento_dia"] / bruto
        total["rendimento_mes"] = round(bruto * (fator ** 21 - 1), 2)
        total["rendimento_ano"] = round(bruto * (fator ** DIAS_UTEIS_ANO - 1), 2)
    else:
        total["rendimento_mes"] = round(total["rendimento_dia"] * 21, 2)
        total["rendimento_ano"] = round(total["rendimento_dia"] * DIAS_UTEIS_ANO, 2)
    total["quantidade"] = len(posicoes)
    return total


def alinhar_series(resultados: list[Resultado]) -> list[dict]:
    """Une as series individuais numa serie unica da carteira.

    Cada investimento tem sua propria grade de datas; usamos a uniao das datas e,
    para cada uma, o ultimo ponto conhecido de cada investimento (step-forward).
    """
    campos = ("base", "bruto", "liquido", "resgatado")
    datas = sorted({p["data"] for r in resultados for p in r.serie})
    if not datas:
        return []
    if len(datas) > MAX_PONTOS_SERIE:
        passo = len(datas) // MAX_PONTOS_SERIE + 1
        # A ultima data e o dia de hoje sempre entram: sao os pontos que o
        # usuario compara com a tabela, e nao podem cair na reamostragem.
        hoje = date.today().isoformat()
        fixas = {datas[0], datas[-1]}
        anteriores = [d for d in datas if d <= hoje]
        if anteriores:
            fixas.add(anteriores[-1])
        datas = sorted(set(datas[::passo]) | fixas)

    cursores = [0] * len(resultados)
    ultimos = [{c: 0.0 for c in campos} for _ in resultados]
    saida = []
    for dt in datas:
        acumulado = {"data": dt, **{c: 0.0 for c in campos}}
        for k, r in enumerate(resultados):
            while cursores[k] < len(r.serie) and r.serie[cursores[k]]["data"] <= dt:
                ultimos[k] = r.serie[cursores[k]]
                cursores[k] += 1
            for c in campos:
                acumulado[c] += ultimos[k][c]
        for c in campos:
            acumulado[c] = round(acumulado[c], 2)
        saida.append(acumulado)
    return saida


def metricas_carteira(motor: Motor, resultados: list[Resultado]) -> dict:
    """XIRR e % do CDI da carteira inteira, a partir do fluxo de caixa somado."""
    if not resultados:
        return {"taxa_anualizada": None, "cdi_periodo": None, "pct_cdi": None}
    fluxos: list[tuple[date, float]] = []
    saldo = 0.0
    for r in resultados:
        fluxos.extend(f for f in r.fluxos if f[0] <= r.hoje.data)
        saldo += r.hoje.liquido
    if saldo > 0:
        fluxos.append((motor.hoje, saldo))
    taxa = xirr(fluxos)
    inicio = min(r.investimento.data_aplicacao for r in resultados)
    cdi = motor.cdi_anualizado(inicio, motor.hoje)
    return {
        "taxa_anualizada": round(taxa, 2) if taxa is not None else None,
        "cdi_periodo": round(cdi, 2) if cdi is not None else None,
        "pct_cdi": (round(taxa / cdi * 100, 1)
                    if taxa is not None and cdi and cdi > 0 else None),
        "desde": inicio.isoformat(),
    }
