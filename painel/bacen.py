"""Cliente das APIs publicas do Banco Central do Brasil.

Duas fontes sao usadas:
  * SGS (Sistema Gerenciador de Series Temporais) - series historicas de CDI,
    Selic, IPCA, TR e poupanca.
  * Olinda / Expectativas de Mercado (boletim Focus) - projecoes de IPCA e Selic
    usadas para estimar o futuro.

Cache em disco com TTL, para que o painel abra rapido e continue funcionando sem
internet (cai para o ultimo valor conhecido e, em ultimo caso, para constantes
de fallback).

O cache e particionado POR ANO (`sgs:12:2024`), nao pelo intervalo pedido. Anos
fechados sao baixados uma unica vez (TTL de 60 dias) e so o ano corrente e
revisitado. A versao anterior usava o intervalo como chave, o que gerava uma
copia inteira da serie a cada dia novo e a cada investimento antigo cadastrado.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode

import requests

log = logging.getLogger(__name__)

SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"
FOCUS_URL = (
    "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/"
    "ExpectativasMercadoAnuais"
)

# Codigos das series no SGS.
SERIE_SELIC_DIARIA = 11      # Taxa Selic efetiva, % ao dia          (desde 1986)
SERIE_CDI_DIARIO = 12        # Taxa DI-Cetip, % ao dia               (desde 1986)
SERIE_SELIC_META = 432       # Meta Selic definida pelo Copom, % ao ano
SERIE_IPCA_MENSAL = 433      # IPCA, variacao % no mes               (desde 1980)
SERIE_CDI_ANUAL = 4389       # Taxa DI acumulada, % ao ano base 252
SERIE_TR_MENSAL = 226        # Taxa Referencial, % no periodo        (desde 1991)
# Poupanca: sao DUAS series, uma por regra legal. A 195 so existe a partir de
# 04/05/2012 (Lei 12.703); antes disso - e para sempre, nos depositos antigos -
# vale a serie 25, que traz 0,5% a.m. composto com a TR.
SERIE_POUPANCA = 195         # Poupanca "nova", % no periodo         (desde 2012)
SERIE_POUPANCA_ANTIGA = 25   # Poupanca "antiga", % no periodo       (desde 1991)

TIMEOUT = 20
TTL_ANO_CORRENTE = timedelta(hours=6)
TTL_ANO_FECHADO = timedelta(days=60)
TTL_PADRAO = timedelta(hours=6)
TTL_FOCUS = timedelta(days=1)

# Usados apenas se nunca houve conexao. Valores de referencia de 2026.
FALLBACK = {
    "selic_meta": 14.25,
    "cdi_anual": 14.15,
    "ipca_12m": 4.80,
    "ipca_projetado": 4.50,
    "poupanca_mensal": 0.6723,
    "tr_mensal": 0.1714,
}


def _hoje() -> date:
    return date.today()


def _fmt(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _parse_data(txt: str) -> date:
    return datetime.strptime(txt, "%d/%m/%Y").date()


def _num(txt: str) -> float:
    return float(str(txt).replace(",", "."))


class Cache:
    """Cache JSON em disco, seguro para uso concorrente pelo Flask."""

    def __init__(self, caminho: Path):
        self.caminho = caminho
        self._lock = threading.Lock()
        self._dados: dict = {}
        self._carregar()

    def _carregar(self) -> None:
        try:
            if self.caminho.exists():
                self._dados = json.loads(self.caminho.read_text(encoding="utf-8"))
        except Exception as exc:  # cache corrompido nao pode derrubar o app
            log.warning("cache ilegivel (%s), recomecando vazio", exc)
            self._dados = {}

    def _salvar(self) -> None:
        try:
            self.caminho.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.caminho.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._dados, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.caminho)
        except Exception as exc:
            log.warning("nao foi possivel gravar o cache: %s", exc)

    def obter(self, chave: str, ttl: timedelta = TTL_PADRAO):
        """Retorna (valor, esta_fresco). Valor vencido ainda e devolvido."""
        with self._lock:
            item = self._dados.get(chave)
        if not item:
            return None, False
        try:
            gravado = datetime.fromisoformat(item["em"])
        except Exception:
            return item.get("v"), False
        return item.get("v"), datetime.now() - gravado < ttl

    def guardar(self, chave: str, valor) -> None:
        with self._lock:
            self._dados[chave] = {"v": valor, "em": datetime.now().isoformat()}
            self._salvar()

    def limpar_legado(self, prefixos: tuple[str, ...]) -> int:
        """Remove chaves do formato antigo (cache por intervalo)."""
        with self._lock:
            mortas = [k for k in self._dados if k.startswith(prefixos)]
            for k in mortas:
                del self._dados[k]
            if mortas:
                self._salvar()
        return len(mortas)


@dataclass
class DadosMercado:
    """Fotografia das taxas usadas pelo motor de calculo."""

    selic_meta: float               # % a.a.
    cdi_anual: float                # % a.a.
    ipca_12m: float                 # % acumulado 12 meses
    ipca_projetado: float           # % a.a. esperado (Focus)
    selic_projetada: float          # % a.a. esperada (Focus)
    poupanca_mensal: float          # % a.m. (ultimo publicado)
    tr_mensal: float                # % a.m. (ultimo publicado)
    atualizado_em: str
    online: bool
    # Series historicas: data ISO -> taxa
    cdi_diario: dict[str, float] = field(default_factory=dict)
    selic_diaria: dict[str, float] = field(default_factory=dict)
    ipca_mensal: dict[str, float] = field(default_factory=dict)      # "AAAA-MM" -> %
    # Poupanca e TR: o SGS publica por data de aniversario. Guardamos os dois
    # recortes para acertar tanto o dia exato quanto o mes de competencia.
    poupanca_por_data: dict[str, float] = field(default_factory=dict)
    poupanca_por_mes: dict[str, float] = field(default_factory=dict)
    poupanca_antiga_por_data: dict[str, float] = field(default_factory=dict)
    poupanca_antiga_por_mes: dict[str, float] = field(default_factory=dict)
    tr_por_data: dict[str, float] = field(default_factory=dict)
    tr_por_mes: dict[str, float] = field(default_factory=dict)
    # Meta Selic historica, so nos dias em que o Copom mudou o valor (degraus).
    # Sem ela, um mes de 2015 sem poupanca publicada cairia na Selic de hoje.
    selic_meta_degraus: dict[str, float] = field(default_factory=dict)
    # serie -> (primeira data, ultima data) efetivamente baixadas. O motor usa
    # isso para AVISAR quando extrapola, em vez de silenciosamente inventar.
    cobertura: dict[str, tuple[str, str]] = field(default_factory=dict)

    def alcance(self, serie: str) -> tuple[str, str] | None:
        return self.cobertura.get(serie)

    def resumo(self) -> dict:
        return {
            "selic_meta": self.selic_meta,
            "cdi_anual": self.cdi_anual,
            "ipca_12m": self.ipca_12m,
            "ipca_projetado": self.ipca_projetado,
            "selic_projetada": self.selic_projetada,
            "poupanca_mensal": self.poupanca_mensal,
            "poupanca_anual": ((1 + self.poupanca_mensal / 100) ** 12 - 1) * 100,
            "tr_mensal": self.tr_mensal,
            "atualizado_em": self.atualizado_em,
            "online": self.online,
            "cobertura": {k: {"de": a, "ate": b} for k, (a, b) in self.cobertura.items()},
        }


class ClienteBacen:
    def __init__(self, caminho_cache: Path):
        self.cache = Cache(caminho_cache)
        # Chaves do formato antigo (`diaria:12:2020-01-01:2026-07-26`) ficavam
        # para sempre e inflavam o arquivo. Uma limpeza na subida resolve.
        removidas = self.cache.limpar_legado(("diaria:", "ipca:"))
        if removidas:
            log.info("cache: %d chaves do formato antigo removidas", removidas)
        self.sessao = requests.Session()
        self.sessao.headers["User-Agent"] = "PainelInvestimentos/1.1"
        self._online = True
        self._memo: DadosMercado | None = None
        self._memo_em: datetime | None = None
        self._memo_ano: int | None = None

    # ---------------------------------------------------------------- SGS ---
    def _sgs(self, codigo: int, inicio: date | None = None, fim: date | None = None,
             ultimos: int | None = None) -> list[dict]:
        url = SGS_URL.format(codigo=codigo)
        params = {"formato": "json"}
        if ultimos:
            url += f"/ultimos/{ultimos}"
        else:
            params["dataInicial"] = _fmt(inicio)
            params["dataFinal"] = _fmt(fim)
        resp = self.sessao.get(url, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def _ttl_do_ano(self, ano: int) -> timedelta:
        return TTL_ANO_CORRENTE if ano >= _hoje().year else TTL_ANO_FECHADO

    def _serie_do_ano(self, codigo: int, ano: int) -> dict[str, float]:
        """Um ano civil de uma serie do SGS, cacheado por (codigo, ano)."""
        chave = f"sgs:{codigo}:{ano}"
        valor, fresco = self.cache.obter(chave, self._ttl_do_ano(ano))
        if fresco:
            return valor
        try:
            bruto = self._sgs(codigo, date(ano, 1, 1), min(date(ano, 12, 31), _hoje()))
            serie = {_parse_data(r["data"]).isoformat(): _num(r["valor"]) for r in bruto}
            self.cache.guardar(chave, serie)
            return serie
        except Exception as exc:
            log.warning("falha na serie %s/%s: %s", codigo, ano, exc)
            self._online = False
            return valor or {}

    def serie_por_data(self, codigo: int, inicio: date, fim: date) -> dict[str, float]:
        """Serie como {data ISO: taxa}, montada a partir dos blocos anuais."""
        ini, f = inicio.isoformat(), fim.isoformat()
        saida: dict[str, float] = {}
        for ano in range(inicio.year, fim.year + 1):
            for k, v in self._serie_do_ano(codigo, ano).items():
                if ini <= k <= f:
                    saida[k] = v
        return saida

    @staticmethod
    def _agrupar_por_mes(serie: dict[str, float]) -> dict[str, float]:
        """PRIMEIRO valor publicado de cada mes.

        Poupanca e TR sao publicadas por data de aniversario: a linha de
        01/06/2020 remunera o periodo 01/06 -> 01/07. Para "o mes de junho" o
        representante natural e o dia 1o, nao o dia 28 (que ja pertence quase
        todo a julho). A versao anterior pegava o ultimo dia do mes, o que
        deslocava o mes de competencia em quase 30 dias.
        """
        saida: dict[str, float] = {}
        for k in sorted(serie, reverse=True):
            saida[k[:7]] = serie[k]
        return saida

    @staticmethod
    def _degraus(serie: dict[str, float]) -> dict[str, float]:
        """So os pontos em que o valor muda - para series em patamar (meta Selic).

        Guardar 250 linhas iguais por ano de meta Selic nao acrescenta nada e
        engorda o cache; o que importa sao as datas de decisao do Copom.
        """
        saida: dict[str, float] = {}
        anterior = None
        for k in sorted(serie):
            if serie[k] != anterior:
                saida[k] = anterior = serie[k]
        return saida

    @staticmethod
    def _alcance(serie: dict[str, float]) -> tuple[str, str] | None:
        return (min(serie), max(serie)) if serie else None

    def _ultimo(self, codigo: int, padrao: float) -> float:
        chave = f"ultimo:{codigo}"
        valor, fresco = self.cache.obter(chave)
        if fresco:
            return valor
        try:
            dados = self._sgs(codigo, ultimos=1)
            v = _num(dados[-1]["valor"])
            self.cache.guardar(chave, v)
            return v
        except Exception as exc:
            log.warning("falha ao ler serie %s: %s", codigo, exc)
            self._online = False
            return valor if valor is not None else padrao

    # -------------------------------------------------------------- Focus ---
    def _focus(self, indicador: str, padrao: float) -> float:
        """Mediana do Focus para o proximo ano-calendario cheio."""
        chave = f"focus:{indicador}"
        valor, fresco = self.cache.obter(chave, TTL_FOCUS)
        if fresco:
            return valor
        try:
            ref = str(_hoje().year + 1)
            params = {
                "$top": "1",
                "$filter": f"Indicador eq '{indicador}' and DataReferencia eq '{ref}'",
                "$orderby": "Data desc",
                "$format": "json",
                # O Olinda exige o campo do $orderby dentro do $select.
                "$select": "Data,Mediana",
            }
            # O Olinda rejeita '+' como separador de espaco no $filter; forcamos %20.
            consulta = urlencode(params, quote_via=quote)
            resp = self.sessao.get(FOCUS_URL, params=consulta, timeout=TIMEOUT)
            resp.raise_for_status()
            linhas = resp.json().get("value", [])
            v = float(linhas[0]["Mediana"]) if linhas else padrao
            self.cache.guardar(chave, v)
            return v
        except Exception as exc:
            log.warning("falha no Focus (%s): %s", indicador, exc)
            self._online = False
            return valor if valor is not None else padrao

    # ------------------------------------------------------------ agregado ---
    @staticmethod
    def ipca_acumulado_12m(serie: dict[str, float]) -> float:
        meses = sorted(serie)[-12:]
        fator = 1.0
        for m in meses:
            fator *= 1 + serie[m] / 100
        return (fator - 1) * 100

    def dados_mercado(self, desde: date | None = None, forcar: bool = False) -> DadosMercado:
        """Monta o pacote de dados de mercado, com memoizacao de 10 minutos."""
        hoje = _hoje()
        inicio = min(desde or (hoje - timedelta(days=365 * 5)), hoje - timedelta(days=90))

        # Com cache por ano, basta comparar o ano inicial para saber se a memoria serve.
        if not forcar and self._memo and self._memo_em and self._memo_ano is not None:
            recente = datetime.now() - self._memo_em < timedelta(minutes=10)
            if recente and self._memo_ano <= inicio.year:
                return self._memo

        self._online = True

        cdi_diario = self.serie_por_data(SERIE_CDI_DIARIO, inicio, hoje)
        selic_diaria = self.serie_por_data(SERIE_SELIC_DIARIA, inicio, hoje)
        # 13 meses extra para fechar o IPCA acumulado de 12 meses - e porque o
        # VNA do IPCA+ referencia sempre o mes anterior ao da data de calculo.
        ipca = self._agrupar_por_mes(
            self.serie_por_data(SERIE_IPCA_MENSAL, inicio - timedelta(days=400), hoje))

        poupanca = self.serie_por_data(SERIE_POUPANCA, inicio - timedelta(days=40), hoje)
        poupanca_antiga = self.serie_por_data(
            SERIE_POUPANCA_ANTIGA, inicio - timedelta(days=40), hoje)
        tr = self.serie_por_data(SERIE_TR_MENSAL, inicio - timedelta(days=40), hoje)
        # A meta Selic historica e o que sustenta a regra da poupanca em meses
        # sem publicacao e o CDI/Selic implicito em qualquer buraco da serie.
        meta = self.serie_por_data(SERIE_SELIC_META, inicio - timedelta(days=400), hoje)

        ultimo_poup = (poupanca[max(poupanca)] if poupanca
                       else self._ultimo(SERIE_POUPANCA, FALLBACK["poupanca_mensal"]))
        ultimo_tr = (tr[max(tr)] if tr
                     else self._ultimo(SERIE_TR_MENSAL, FALLBACK["tr_mensal"]))

        cobertura = {
            nome: alcance
            for nome, alcance in (
                ("cdi_diario", self._alcance(cdi_diario)),
                ("selic_diaria", self._alcance(selic_diaria)),
                ("ipca_mensal", self._alcance(ipca)),
                ("tr", self._alcance(tr)),
                ("poupanca_nova", self._alcance(poupanca)),
                ("poupanca_antiga", self._alcance(poupanca_antiga)),
                ("selic_meta", self._alcance(meta)),
            )
            if alcance is not None
        }

        dados = DadosMercado(
            selic_meta=self._ultimo(SERIE_SELIC_META, FALLBACK["selic_meta"]),
            cdi_anual=self._ultimo(SERIE_CDI_ANUAL, FALLBACK["cdi_anual"]),
            ipca_12m=self.ipca_acumulado_12m(ipca) if ipca else FALLBACK["ipca_12m"],
            ipca_projetado=self._focus("IPCA", FALLBACK["ipca_projetado"]),
            selic_projetada=self._focus("Selic", FALLBACK["selic_meta"]),
            poupanca_mensal=ultimo_poup,
            tr_mensal=ultimo_tr,
            atualizado_em=datetime.now().isoformat(timespec="seconds"),
            online=self._online,
            cdi_diario=cdi_diario,
            selic_diaria=selic_diaria,
            ipca_mensal=ipca,
            poupanca_por_data=poupanca,
            poupanca_por_mes=self._agrupar_por_mes(poupanca),
            poupanca_antiga_por_data=poupanca_antiga,
            poupanca_antiga_por_mes=self._agrupar_por_mes(poupanca_antiga),
            tr_por_data=tr,
            tr_por_mes=self._agrupar_por_mes(tr),
            selic_meta_degraus=self._degraus(meta),
            cobertura=cobertura,
        )
        self._memo, self._memo_em, self._memo_ano = dados, datetime.now(), inicio.year
        return dados
