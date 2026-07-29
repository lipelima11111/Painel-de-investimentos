"""Persistencia em SQLite - um arquivo unico ao lado do programa."""

from __future__ import annotations

import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path

from .catalogo import INDEXADORES, ISENCAO_CUSTODIA_TESOURO_SELIC, TIPOS

ESQUEMA = """
CREATE TABLE IF NOT EXISTS investimentos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nome            TEXT    NOT NULL,
    tipo            TEXT    NOT NULL,
    indexador       TEXT    NOT NULL,
    taxa            REAL    NOT NULL DEFAULT 0,
    valor_aplicado  REAL    NOT NULL,
    aporte_mensal   REAL    NOT NULL DEFAULT 0,
    data_aplicacao  TEXT    NOT NULL,
    data_vencimento TEXT,
    instituicao     TEXT    NOT NULL DEFAULT '',
    observacoes     TEXT    NOT NULL DEFAULT '',
    criado_em       TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inv_tipo ON investimentos(tipo);

CREATE TABLE IF NOT EXISTS resgates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    investimento_id INTEGER NOT NULL REFERENCES investimentos(id) ON DELETE CASCADE,
    data            TEXT    NOT NULL,
    valor           REAL,
    criado_em       TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_resg_inv ON resgates(investimento_id);
"""


class ErroValidacao(ValueError):
    """Dados enviados pelo usuario que nao passam na validacao."""


def _conectar(caminho: Path) -> sqlite3.Connection:
    con = sqlite3.connect(caminho, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


class Repositorio:
    """Todo acesso de escrita passa por `self._lock`.

    O servidor de desenvolvimento do Flask (e o Waitress, em producao) atende
    requisicoes em threads diferentes sobre a mesma conexao sqlite3
    (`check_same_thread=False`). Sem um lock, duas escritas concorrentes podem
    intercalar e corromper o WAL; leituras continuam livres.
    """

    def __init__(self, caminho: Path):
        self.caminho = caminho
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self.con = _conectar(caminho)
        self._lock = threading.Lock()
        with self._lock:
            self.con.executescript(ESQUEMA)
            self.con.commit()

    # ------------------------------------------------------------ validacao --
    @staticmethod
    def validar(dados: dict) -> dict:
        def texto(campo: str, obrigatorio: bool = False, maximo: int = 120) -> str:
            v = str(dados.get(campo, "") or "").strip()[:maximo]
            if obrigatorio and not v:
                raise ErroValidacao(f"O campo '{campo}' e obrigatorio.")
            return v

        def numero(campo: str, minimo: float = 0.0, maximo: float | None = None,
                   padrao: float | None = None) -> float:
            bruto = dados.get(campo, padrao)
            if bruto in (None, ""):
                if padrao is None:
                    raise ErroValidacao(f"O campo '{campo}' e obrigatorio.")
                return padrao
            try:
                v = float(str(bruto).replace(",", "."))
            except (TypeError, ValueError):
                raise ErroValidacao(f"O campo '{campo}' precisa ser um numero.")
            if v != v or v in (float("inf"), float("-inf")):
                raise ErroValidacao(f"O campo '{campo}' precisa ser um numero valido.")
            if v < minimo:
                raise ErroValidacao(f"O campo '{campo}' nao pode ser menor que {minimo}.")
            if maximo is not None and v > maximo:
                raise ErroValidacao(f"O campo '{campo}' nao pode ser maior que {maximo}.")
            return v

        def data(campo: str, obrigatorio: bool = False) -> str | None:
            v = str(dados.get(campo, "") or "").strip()
            if not v:
                if obrigatorio:
                    raise ErroValidacao(f"O campo '{campo}' e obrigatorio.")
                return None
            try:
                return date.fromisoformat(v).isoformat()
            except ValueError:
                raise ErroValidacao(f"Data invalida em '{campo}' (use AAAA-MM-DD).")

        tipo = texto("tipo", obrigatorio=True)
        if tipo not in TIPOS:
            raise ErroValidacao(f"Tipo de investimento desconhecido: {tipo}")

        indexador = texto("indexador", obrigatorio=True)
        if indexador not in INDEXADORES:
            raise ErroValidacao(f"Indexador desconhecido: {indexador}")
        if indexador not in TIPOS[tipo]["indexadores"]:
            permitidos = ", ".join(TIPOS[tipo]["indexadores"])
            raise ErroValidacao(
                f"{TIPOS[tipo]['nome']} nao aceita o indexador {indexador}. "
                f"Permitidos: {permitidos}."
            )

        aplicacao = data("data_aplicacao", obrigatorio=True)
        vencimento = data("data_vencimento")
        if vencimento and vencimento <= aplicacao:
            raise ErroValidacao("O vencimento precisa ser depois da data de aplicacao.")
        if date.fromisoformat(aplicacao) > date.today():
            raise ErroValidacao("A data de aplicacao nao pode estar no futuro.")

        maximo_taxa = INDEXADORES[indexador].get("maximo")

        limpo = {
            "nome": texto("nome", obrigatorio=True),
            "tipo": tipo,
            "indexador": indexador,
            "taxa": numero("taxa", minimo=0.0, maximo=maximo_taxa or None, padrao=0.0),
            "valor_aplicado": numero("valor_aplicado", minimo=0.01, maximo=1_000_000_000),
            "aporte_mensal": numero("aporte_mensal", minimo=0.0, maximo=1_000_000_000, padrao=0.0),
            "data_aplicacao": aplicacao,
            "data_vencimento": vencimento,
            "instituicao": texto("instituicao"),
            "observacoes": texto("observacoes", maximo=500),
        }
        if indexador != "POUPANCA" and limpo["taxa"] <= 0:
            raise ErroValidacao("Informe a taxa contratada do investimento.")
        return limpo

    @staticmethod
    def validar_resgate(dados: dict, data_aplicacao: str) -> dict:
        v = str(dados.get("valor", "") or "").strip()
        valor = None
        if v:
            try:
                valor = float(v.replace(",", "."))
            except ValueError:
                raise ErroValidacao("Valor do resgate precisa ser um numero.")
            if valor <= 0:
                raise ErroValidacao("Valor do resgate precisa ser maior que zero.")
        data_txt = str(dados.get("data", "") or "").strip()
        if not data_txt:
            raise ErroValidacao("Informe a data do resgate.")
        try:
            d = date.fromisoformat(data_txt)
        except ValueError:
            raise ErroValidacao("Data invalida (use AAAA-MM-DD).")
        if d > date.today():
            raise ErroValidacao("A data do resgate nao pode estar no futuro.")
        if d < date.fromisoformat(data_aplicacao):
            raise ErroValidacao("O resgate nao pode ser anterior a aplicacao.")
        return {"data": d.isoformat(), "valor": valor}

    # --------------------------------------------------------------- acesso --
    def listar(self) -> list[dict]:
        cur = self.con.execute("SELECT * FROM investimentos ORDER BY data_aplicacao, id")
        linhas = [dict(r) for r in cur.fetchall()]
        self._anexar_resgates(linhas)
        self._ratear_isencao_custodia(linhas)
        return linhas

    def _anexar_resgates(self, linhas: list[dict]) -> None:
        if not linhas:
            return
        ids = [l["id"] for l in linhas]
        marcadores = ",".join("?" * len(ids))
        cur = self.con.execute(
            f"SELECT * FROM resgates WHERE investimento_id IN ({marcadores}) "
            "ORDER BY data, id", ids)
        por_investimento: dict[int, list[dict]] = {}
        for r in cur.fetchall():
            por_investimento.setdefault(r["investimento_id"], []).append(dict(r))
        for l in linhas:
            l["resgates"] = por_investimento.get(l["id"], [])

    @staticmethod
    def _ratear_isencao_custodia(linhas: list[dict]) -> None:
        """A isencao de R$ 10 mil de custodia e por CONTA, nao por titulo.

        Quem tem N posicoes de Tesouro Selic ativas divide o beneficio entre
        elas (proporcional ao valor aplicado), em vez de cada uma reivindicar
        os 10 mil inteiros.
        """
        ativos = [l for l in linhas if l["tipo"] == "TESOURO_SELIC"
                  and not _encerrado(l)]
        total = sum(l["valor_aplicado"] for l in ativos) or 1.0
        for l in linhas:
            l["isencao_custodia"] = 0.0
        for l in ativos:
            peso = l["valor_aplicado"] / total
            l["isencao_custodia"] = round(ISENCAO_CUSTODIA_TESOURO_SELIC * peso, 2)

    def obter(self, inv_id: int) -> dict | None:
        cur = self.con.execute("SELECT * FROM investimentos WHERE id = ?", (inv_id,))
        row = cur.fetchone()
        if not row:
            return None
        linha = dict(row)
        self._anexar_resgates([linha])
        todos = self.listar()
        atual = next((l for l in todos if l["id"] == inv_id), linha)
        return atual

    def criar(self, dados: dict) -> dict:
        d = self.validar(dados)
        d["criado_em"] = datetime.now().isoformat(timespec="seconds")
        colunas = ", ".join(d)
        marcas = ", ".join("?" for _ in d)
        with self._lock:
            cur = self.con.execute(
                f"INSERT INTO investimentos ({colunas}) VALUES ({marcas})", tuple(d.values())
            )
            self.con.commit()
        return self.obter(cur.lastrowid)

    def atualizar(self, inv_id: int, dados: dict) -> dict | None:
        if not self.con.execute(
                "SELECT 1 FROM investimentos WHERE id = ?", (inv_id,)).fetchone():
            return None
        d = self.validar(dados)
        sets = ", ".join(f"{c} = ?" for c in d)
        with self._lock:
            self.con.execute(
                f"UPDATE investimentos SET {sets} WHERE id = ?", (*d.values(), inv_id)
            )
            self.con.commit()
        return self.obter(inv_id)

    def remover(self, inv_id: int) -> bool:
        with self._lock:
            cur = self.con.execute("DELETE FROM investimentos WHERE id = ?", (inv_id,))
            self.con.commit()
        return cur.rowcount > 0

    def adicionar_resgate(self, inv_id: int, dados: dict) -> dict | None:
        linha = self.con.execute(
            "SELECT data_aplicacao FROM investimentos WHERE id = ?", (inv_id,)).fetchone()
        if not linha:
            return None
        r = self.validar_resgate(dados, linha["data_aplicacao"])
        with self._lock:
            self.con.execute(
                "INSERT INTO resgates (investimento_id, data, valor, criado_em) "
                "VALUES (?, ?, ?, ?)",
                (inv_id, r["data"], r["valor"], datetime.now().isoformat(timespec="seconds")),
            )
            self.con.commit()
        return self.obter(inv_id)

    def remover_resgate(self, inv_id: int, resgate_id: int) -> dict | None:
        with self._lock:
            cur = self.con.execute(
                "DELETE FROM resgates WHERE id = ? AND investimento_id = ?",
                (resgate_id, inv_id))
            self.con.commit()
        if cur.rowcount == 0:
            return None
        return self.obter(inv_id)

    def data_mais_antiga(self) -> date | None:
        cur = self.con.execute("SELECT MIN(data_aplicacao) AS m FROM investimentos")
        m = cur.fetchone()["m"]
        return date.fromisoformat(m) if m else None


def _encerrado(linha: dict) -> bool:
    """Uma posicao esta encerrada se venceu ou teve resgate total registrado."""
    venc = linha.get("data_vencimento")
    if venc and date.fromisoformat(venc) <= date.today():
        return True
    return any(r.get("valor") in (None, 0) for r in linha.get("resgates", []))
