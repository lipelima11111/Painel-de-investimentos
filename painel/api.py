"""Aplicacao Flask: rotas JSON + entrega da pagina do painel."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from .bacen import ClienteBacen
from .calculos import Investimento, Motor, alinhar_series, consolidar, metricas_carteira
from .catalogo import CENARIOS, TETO_FGC, TIPOS, catalogo_publico
from .database import ErroValidacao, Repositorio

log = logging.getLogger(__name__)
BASE = Path(__file__).resolve().parent
DADOS = BASE.parent / "dados"


def _data(param: str, padrao: date) -> date:
    bruto = request.args.get(param)
    if not bruto:
        return padrao
    try:
        return date.fromisoformat(bruto)
    except ValueError:
        raise ErroValidacao(f"Parametro '{param}' deve estar em AAAA-MM-DD.")


def _brl(v: float) -> str:
    """Formata no padrao brasileiro: R$ 1.234.567,89"""
    return "R$ " + f"{v:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _anos(padrao: float = 5.0) -> float:
    try:
        v = float(request.args.get("anos", padrao))
    except ValueError:
        raise ErroValidacao("Parametro 'anos' invalido.")
    return min(max(v, 0.08), 50.0)


def _cenario(padrao: str = "base") -> str:
    v = request.args.get("cenario", padrao)
    if v not in CENARIOS:
        raise ErroValidacao(f"Cenario desconhecido: {v}")
    return v


def _corpo_json() -> dict:
    """So aceita corpo JSON de verdade - recusa forms/text para dificultar CSRF."""
    if not request.is_json:
        raise ErroValidacao("Envie o corpo como JSON (Content-Type: application/json).")
    return request.get_json(silent=True) or {}


def _mais_anos(d: date, n: float) -> date:
    """Avanca `n` anos mantendo o dia do mes (29/02 vira 28/02).

    Somar 365,25 dias faz o marco de 2 anos cair um dia antes do de 1 e 3 anos,
    o que fica estranho na tabela "daqui a N anos".
    """
    if n != int(n):
        return d + timedelta(days=round(365.25 * n))
    try:
        return d.replace(year=d.year + int(n))
    except ValueError:
        return d.replace(year=d.year + int(n), day=28)


def criar_app(caminho_dados: Path | None = None) -> Flask:
    pasta = caminho_dados or DADOS
    pasta.mkdir(parents=True, exist_ok=True)

    app = Flask(__name__, template_folder=str(BASE / "templates"),
                static_folder=str(BASE / "static"))
    app.json.sort_keys = False
    repo = Repositorio(pasta / "investimentos.db")
    bacen = ClienteBacen(pasta / "cache_bacen.json")

    def motor(cenario: str = "base") -> Motor:
        """Motor carregado com historico suficiente para o investimento mais antigo."""
        dados = bacen.dados_mercado(desde=repo.data_mais_antiga())
        delta = CENARIOS.get(cenario, CENARIOS["base"])["delta_selic"]
        return Motor(dados, delta_selic=delta)

    # ------------------------------------------------------------- erros ---
    @app.errorhandler(ErroValidacao)
    def _erro_validacao(e):
        return jsonify({"erro": str(e)}), 400

    @app.errorhandler(HTTPException)
    def _erro_http(e):
        # 404/405/etc sao erros esperados do roteamento - nao sao "erro interno".
        # Sem este handler explicito, o @app.errorhandler(Exception) generico
        # abaixo capturava tambem estes (o Flask sobe a MRO de excecoes) e
        # respondia 500 para um simples "metodo nao permitido".
        if request.path.startswith("/api/"):
            return jsonify({"erro": e.description or e.name}), e.code
        if e.code == 404:
            return render_template("index.html"), 200
        return e

    @app.errorhandler(Exception)
    def _erro_interno(e):
        log.exception("erro nao tratado em %s", request.path)
        return jsonify({"erro": "Erro interno. Veja o log do servidor para detalhes."}), 500

    # ------------------------------------------------------------ paginas ---
    @app.get("/")
    def index():
        return render_template("index.html")

    # ------------------------------------------------------------ mercado ---
    @app.get("/api/catalogo")
    def catalogo():
        return jsonify(catalogo_publico())

    @app.get("/api/mercado")
    def mercado():
        forcar = request.args.get("atualizar") == "1"
        dados = bacen.dados_mercado(desde=repo.data_mais_antiga(), forcar=forcar)
        m = Motor(dados)
        resumo = dados.resumo()
        resumo["poupanca_regra"] = round(m.taxa_poupanca_mes(), 4)
        resumo["cdi_diario"] = round(m._tdi(date.today()) * 100, 6)
        resumo["juro_real"] = round(
            ((1 + dados.cdi_anual / 100) / (1 + dados.ipca_12m / 100) - 1) * 100, 2
        )
        return jsonify(resumo)

    # ------------------------------------------------------ investimentos ---
    @app.get("/api/investimentos")
    def listar():
        mt = motor()
        saida = []
        for linha in repo.listar():
            inv = Investimento.de_linha(linha)
            inv.isencao_custodia = linha.get("isencao_custodia", inv.isencao_custodia)
            r = mt.avaliar_hoje(inv)
            saida.append({
                **linha,
                "posicao": r.hoje.dict(),
                "detalhes": mt.detalhes(inv, r),
                "tipo_nome": TIPOS[inv.tipo]["nome"],
                "eventos": r.eventos,
            })
        return jsonify(saida)

    @app.post("/api/investimentos")
    def criar():
        linha = repo.criar(_corpo_json())
        mt = motor()
        inv = Investimento.de_linha(linha)
        r = mt.avaliar_hoje(inv)
        return jsonify({**linha, "posicao": r.hoje.dict(),
                        "detalhes": mt.detalhes(inv, r)}), 201

    @app.put("/api/investimentos/<int:inv_id>")
    def atualizar(inv_id: int):
        linha = repo.atualizar(inv_id, _corpo_json())
        if not linha:
            return jsonify({"erro": "Investimento nao encontrado."}), 404
        mt = motor()
        inv = Investimento.de_linha(linha)
        inv.isencao_custodia = linha.get("isencao_custodia", inv.isencao_custodia)
        r = mt.avaliar_hoje(inv)
        return jsonify({**linha, "posicao": r.hoje.dict(), "detalhes": mt.detalhes(inv, r)})

    @app.delete("/api/investimentos/<int:inv_id>")
    def remover(inv_id: int):
        if not repo.remover(inv_id):
            return jsonify({"erro": "Investimento nao encontrado."}), 404
        return jsonify({"ok": True})

    @app.get("/api/investimentos/<int:inv_id>/evolucao")
    def evolucao(inv_id: int):
        linha = repo.obter(inv_id)
        if not linha:
            return jsonify({"erro": "Investimento nao encontrado."}), 404
        inv = Investimento.de_linha(linha)
        inv.isencao_custodia = linha.get("isencao_custodia", inv.isencao_custodia)
        anos = _anos()
        fim = _data("ate", _mais_anos(date.today(), anos))
        mt = motor(_cenario())
        r = mt.simular(inv, fim)
        return jsonify({
            "investimento": linha,
            "hoje": r.hoje.dict(),
            "final": r.final.dict(),
            "serie": r.serie,
            "detalhes": mt.detalhes(inv, r),
            "eventos": r.eventos,
            "encerrado": r.encerrado,
        })

    # ---------------------------------------------------------- resgates ---
    @app.post("/api/investimentos/<int:inv_id>/resgates")
    def criar_resgate(inv_id: int):
        linha = repo.adicionar_resgate(inv_id, _corpo_json())
        if not linha:
            return jsonify({"erro": "Investimento nao encontrado."}), 404
        mt = motor()
        inv = Investimento.de_linha(linha)
        inv.isencao_custodia = linha.get("isencao_custodia", inv.isencao_custodia)
        r = mt.avaliar_hoje(inv)
        return jsonify({**linha, "posicao": r.hoje.dict(), "detalhes": mt.detalhes(inv, r),
                        "eventos": r.eventos}), 201

    @app.delete("/api/investimentos/<int:inv_id>/resgates/<int:resgate_id>")
    def remover_resgate(inv_id: int, resgate_id: int):
        linha = repo.remover_resgate(inv_id, resgate_id)
        if not linha:
            return jsonify({"erro": "Resgate nao encontrado."}), 404
        mt = motor()
        inv = Investimento.de_linha(linha)
        inv.isencao_custodia = linha.get("isencao_custodia", inv.isencao_custodia)
        r = mt.avaliar_hoje(inv)
        return jsonify({**linha, "posicao": r.hoje.dict(), "detalhes": mt.detalhes(inv, r)})

    # ----------------------------------------------------------- carteira ---
    def _investimentos_carregados(mt: Motor) -> list[Investimento]:
        invs = []
        for linha in repo.listar():
            inv = Investimento.de_linha(linha)
            inv.isencao_custodia = linha.get("isencao_custodia", inv.isencao_custodia)
            invs.append(inv)
        return invs

    @app.get("/api/carteira")
    def carteira():
        mt = motor()
        invs = _investimentos_carregados(mt)
        if not invs:
            return jsonify({
                "resumo": consolidar([]), "metricas": metricas_carteira(mt, []),
                "por_tipo": [], "por_indexador": [], "por_instituicao": [],
                "vencimentos": [], "alertas": [],
            })

        resultados, por_tipo, por_ix, por_inst = [], {}, {}, {}
        hoje = date.today()
        vencimentos, alertas = [], []

        for inv in invs:
            r = mt.avaliar_hoje(inv)
            resultados.append(r)
            v = r.hoje.liquido
            if v <= 0 and r.encerrado:
                continue  # posicao zerada por resgate total nao entra na alocacao

            nome_tipo = TIPOS[inv.tipo]["nome"]
            por_tipo[nome_tipo] = por_tipo.get(nome_tipo, 0) + v
            por_ix[inv.indexador] = por_ix.get(inv.indexador, 0) + v
            chave_inst = inv.instituicao or "Nao informada"
            por_inst.setdefault(chave_inst, {"valor": 0.0, "fgc": 0.0})
            por_inst[chave_inst]["valor"] += v
            if TIPOS[inv.tipo]["fgc"]:
                por_inst[chave_inst]["fgc"] += v

            if inv.data_vencimento and not r.encerrado:
                vencimentos.append({
                    "id": inv.id, "nome": inv.nome,
                    "data_aplicacao": inv.data_aplicacao.isoformat(),
                    "data": inv.data_vencimento.isoformat(),
                    "dias": (inv.data_vencimento - hoje).days,
                    "valor": r.hoje.liquido,
                })

            faixa = mt.detalhes(inv).get("proxima_faixa_ir")
            if faixa and faixa["dias_restantes"] <= 45:
                alertas.append({
                    "nivel": "info", "id": inv.id,
                    "texto": (f"{inv.nome}: em {faixa['dias_restantes']} dias o IR cai de "
                              f"{faixa['aliquota_atual']:.1f}% para {faixa['proxima_aliquota']:.1f}%."),
                })

        for inst, dados in por_inst.items():
            if dados["fgc"] > TETO_FGC:
                excedente = dados["fgc"] - TETO_FGC
                alertas.append({
                    "nivel": "alerta", "id": None,
                    "texto": (f"{inst}: voce tem {_brl(dados['fgc'])} em produtos com FGC, "
                              f"{_brl(excedente)} acima do teto de {_brl(TETO_FGC)} por CPF "
                              f"e instituicao. Esse excedente nao estaria coberto."),
                })
        for v in sorted(vencimentos, key=lambda x: x["dias"]):
            if 0 <= v["dias"] <= 30:
                alertas.append({"nivel": "info", "id": v["id"],
                                "texto": f"{v['nome']} vence em {v['dias']} dias."})
        # Trechos em que alguma taxa passada nao veio da serie oficial do BACEN.
        # O motor acumula os avisos ao longo de todas as simulacoes da carteira.
        for texto in mt.avisos:
            alertas.append({"nivel": "alerta", "id": None, "texto": texto})

        def fatias(d: dict) -> list[dict]:
            total = sum(d.values()) or 1
            return sorted(
                [{"rotulo": k, "valor": round(v, 2), "peso": round(100 * v / total, 2)}
                 for k, v in d.items()],
                key=lambda x: -x["valor"],
            )

        return jsonify({
            "resumo": consolidar([r.hoje for r in resultados]),
            "metricas": metricas_carteira(mt, resultados),
            "por_tipo": fatias(por_tipo),
            "por_indexador": fatias(por_ix),
            "por_instituicao": fatias({k: v["valor"] for k, v in por_inst.items()}),
            "vencimentos": sorted(vencimentos, key=lambda x: x["dias"]),
            "alertas": alertas,
        })

    @app.get("/api/carteira/evolucao")
    def carteira_evolucao():
        # historico=1 para so o passado (aba Carteira); senao projeta N anos.
        somente_historico = request.args.get("historico") == "1"
        anos = _anos()
        hoje = date.today()
        fim = hoje if somente_historico else _mais_anos(hoje, anos)
        invs = repo.listar()
        if not invs:
            return jsonify({"serie": [], "marcos": [], "hoje": hoje.isoformat()})

        # Uma unica passada por investimento produz a serie e todos os marcos.
        datas_marco = ([] if somente_historico else
                       [_mais_anos(hoje, n) for n in range(1, int(anos) + 1)])
        mt = motor(_cenario())
        resultados = []
        for l in invs:
            inv = Investimento.de_linha(l)
            inv.isencao_custodia = l.get("isencao_custodia", inv.isencao_custodia)
            resultados.append(mt.simular(inv, fim, marcos=datas_marco))

        marcos = []
        for n, alvo in enumerate(datas_marco, start=1):
            iso = alvo.isoformat()
            total = consolidar([r.marcos[iso] for r in resultados if iso in r.marcos])
            marcos.append({
                "ano": n, "data": iso,
                "principal": total["principal"], "liquido": total["liquido"],
                "rendimento_liquido": total["rendimento_liquido"],
            })

        return jsonify({
            "serie": alinhar_series(resultados),
            "marcos": marcos,
            "hoje": hoje.isoformat(),
        })

    # ---------------------------------------------------------- simulador ---
    @app.post("/api/simulador")
    def simulador():
        corpo = _corpo_json()
        cenarios = corpo.get("cenarios") or []
        if not cenarios:
            raise ErroValidacao("Envie ao menos um cenario para simular.")
        if len(cenarios) > 8:
            raise ErroValidacao("Limite de 8 cenarios por simulacao.")

        try:
            meses = int(corpo.get("prazo_meses", 12))
        except (TypeError, ValueError):
            raise ErroValidacao("Prazo invalido.")
        meses = min(max(meses, 1), 600)

        inicio = date.today()
        fim = inicio + timedelta(days=round(30.44 * meses))
        mt = motor()

        saida = []
        for c in cenarios:
            dados = {
                "nome": c.get("nome") or TIPOS.get(c.get("tipo", ""), {}).get("nome", "Cenario"),
                "tipo": c.get("tipo"),
                "indexador": c.get("indexador"),
                "taxa": c.get("taxa", 0),
                "valor_aplicado": corpo.get("valor_aplicado", 1000),
                "aporte_mensal": corpo.get("aporte_mensal", 0),
                "data_aplicacao": inicio.isoformat(),
            }
            inv = Investimento.de_linha(Repositorio.validar(dados) | {"id": None})
            r = mt.simular(inv, fim)
            saida.append({
                "nome": dados["nome"],
                "tipo": inv.tipo,
                "tipo_nome": TIPOS[inv.tipo]["nome"],
                "indexador": inv.indexador,
                "taxa": inv.taxa,
                "isento_ir": TIPOS[inv.tipo]["isento_ir"],
                "taxa_anual_equivalente": round(mt.taxa_anual_equivalente(inv), 2),
                "final": r.final.dict(),
                "serie": r.serie,
            })

        saida.sort(key=lambda x: -x["final"]["liquido"])
        melhor = saida[0]["final"]["liquido"] if saida else 0
        for s in saida:
            s["diferenca_para_melhor"] = round(s["final"]["liquido"] - melhor, 2)
        return jsonify({"prazo_meses": meses, "vencimento": fim.isoformat(),
                        "resultados": saida})

    # ----------------------------------------------------- taxa equivalente --
    @app.post("/api/equivalencia")
    def equivalencia():
        """Quanto um isento (LCI/LCA) precisa render para empatar com um tributado."""
        corpo = _corpo_json()
        try:
            pct_cdi = float(corpo.get("percentual_cdi", 100))
            meses = int(corpo.get("prazo_meses", 12))
        except (TypeError, ValueError):
            raise ErroValidacao("Parametros invalidos.")
        from .catalogo import aliquota_ir
        dias = round(30.44 * min(max(meses, 1), 600))
        aliq = aliquota_ir(dias) / 100
        return jsonify({
            "prazo_meses": meses,
            "dias": dias,
            "aliquota_ir": round(aliq * 100, 2),
            "percentual_cdi_tributado": pct_cdi,
            "percentual_cdi_isento_equivalente": round(pct_cdi * (1 - aliq), 2),
        })

    return app
