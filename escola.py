"""Escola de Traders: testa cada aluno (estratégia) de forma honesta, com walk-forward.

Como funciona:
  • O período é dividido em 8 provas de 6 meses (4 anos, desde o fim de 2022). Antes de cada
    prova o aluno ESTUDA os 2 anos anteriores (escolhe os melhores parâmetros dele) e depois é
    AVALIADO nos 6 meses seguintes, que nunca viu. A nota vem só dessas provas "fora da amostra".
  • Ele opera uma carteira com BTC, ETH, SOL e BNB (25% em cada), pagando 0,1% de taxa
    + 0,05% de derrapagem em cada compra e venda. Também refaz as provas com custo dobrado.
  • Como testamos muitos alunos, um deles pode ir bem por SORTE. O "Deflated Sharpe" desconta isso.
  • Passa de ano quem lucra fora da amostra com risco controlado, consistência e confiança estatística.
"""
import bisect
import json
import math
import os
import statistics
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import historico
import indicadores
from estrategias import BARRAS_POR_DIA, TODAS, POR_ID, checar_saida, fracao_entrada, niveis_de_entrada, pode_entrar
from motor_futuros import dimensionar, espelho

AQUI = Path(__file__).resolve().parent
ARQ_ESCOLA = AQUI / "dados" / "escola.json"
DIA = 86_400_000

PADRAO = {
    "pares": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"],
    "treino_dias": 730,
    "teste_dias": 182,
    "provas": 8,
    "taxa": 0.001,
    "derrapagem": 0.0005,
    "aprovacao": {"sharpe_min": 0.6, "profit_factor_min": 1.2, "trades_min": 30, "consistencia_min": 0.55,
                  "queda_max_pct": -40.0, "dsr_min": 0.90},
}


# ---------------------------------------------------------------------------
def backtest(est, v, d, p, ini, fim, taxa, derrap):
    """Simula entre os índices [ini, fim) com capital 1.0.
    Devolve (curva diária {dia: patrimônio}, retornos por operação, exposição média 0..1)."""
    if est.tipo == "peso":
        return _backtest_peso(est, v, d, p, ini, fim, taxa, derrap)
    caixa, unidades, pos = 1.0, 0.0, None
    curva, trades, exp = {}, [], 0.0
    t, c = v["t"], v["c"]
    for i in range(ini, fim):
        if pos:
            r = checar_saida(est, d, v, i, p, pos)
            if r or i == fim - 1:
                preco = (r[0] if r else c[i]) * (1 - derrap)
                caixa += unidades * preco * (1 - taxa)
                trades.append(caixa / pos["eq"] - 1)
                unidades, pos = 0.0, None
        elif i < fim - 1 and pode_entrar(est, d, v, i, p):
            eq = caixa
            investe = eq * fracao_entrada(d, i, p)
            unidades = investe * (1 - taxa) / (c[i] * (1 + derrap))
            caixa -= investe
            stop, alvo = niveis_de_entrada(d, i, p, c[i])
            pos = {"preco": c[i], "stop": stop, "alvo": alvo, "eq": eq, "barras": 0, "maxc": c[i]}
        eq = caixa + unidades * c[i]
        if unidades:
            exp += unidades * c[i] / eq
        curva[t[i] // DIA] = eq
    return curva, trades, exp / max(fim - ini, 1)


def _backtest_peso(est, v, d, p, ini, fim, taxa, derrap):
    caixa, unidades = 1.0, 0.0
    curva, trades, exp = {}, [], 0.0
    eq_abertura = None
    t, c = v["t"], v["c"]
    for i in range(ini, fim):
        preco = c[i]
        eq = caixa + unidades * preco
        alvo = est.peso(d, v, i, p) if i < fim - 1 else 0.0
        atual = unidades * preco / eq if eq > 0 else 0.0
        if (alvo == 0 and unidades > 0) or abs(alvo - atual) >= 0.1:
            if alvo == 0:
                caixa += unidades * preco * (1 - derrap) * (1 - taxa)
                unidades = 0.0
            else:
                delta = alvo * eq - unidades * preco
                if delta > 0:
                    unidades += delta * (1 - taxa) / (preco * (1 + derrap))
                    caixa -= delta
                else:
                    vende = min(unidades, -delta / preco)
                    caixa += vende * preco * (1 - derrap) * (1 - taxa)
                    unidades -= vende
            if unidades > 0 and eq_abertura is None:
                eq_abertura = eq
            if unidades == 0 and eq_abertura is not None:
                trades.append(caixa / eq_abertura - 1)
                eq_abertura = None
        eq = caixa + unidades * preco
        exp += unidades * preco / eq if eq > 0 else 0.0
        curva[t[i] // DIA] = eq
    return curva, trades, exp / max(fim - ini, 1)


def backtest_futuros(est, v, d, ve, de, p, ini, fim, cf, reg, custo=1.0):
    """Futuros: LONG e SHORT (short = sinal no preço espelhado), o MESMO julgamento de tamanho e alavancagem
    do motor ao vivo (risco fixo pela distância do stop), taxas, derrapagem, funding e liquidação."""
    taxa = (cf.get("taxa_taker", 0.0005) + cf.get("derrapagem", 0.0002)) * custo
    fund = cf.get("funding_8h", 0.00005) * (24 / BARRAS_POR_DIA[p["intervalo"]]) / 8
    mmr = cf.get("margem_manutencao", 0.005)
    cfj = dict(cf, taxa_taker=taxa, derrapagem=0.0)
    t, o, h, l, c = v["t"], v["o"], v["h"], v["l"], v["c"]
    eq, pos, curva, trades, exp = 1.0, None, {}, [], 0.0
    peso = est.tipo == "peso"
    for i in range(ini, fim):
        if pos:
            lado, N, px0 = pos["lado"], pos["N"], pos["px"]
            pos["custos"] += lado * N * (c[i] / px0) * fund
            sai = None
            liq, st = pos["liq"], pos["stop"]
            if pos["m"]:
                st = pos["m"]["stop"] if lado > 0 else 1 / pos["m"]["stop"]
            if lado > 0 and l[i] <= liq and (o[i] <= liq or st <= liq):
                sai = "liq"
            elif lado < 0 and h[i] >= liq and (o[i] >= liq or st >= liq):
                sai = "liq"
            elif peso:
                if lado > 0 and l[i] <= st:
                    sai = min(st, o[i])
                elif lado < 0 and h[i] >= st:
                    sai = max(st, o[i])
                else:
                    net = est.peso(d, v, i, p) - est.peso(de, ve, i, p)
                    if abs(net) < 0.05 or (net > 0) != (lado > 0):
                        sai = c[i]
            else:
                r = checar_saida(est, d if lado > 0 else de, v if lado > 0 else ve, i, p, pos["m"])
                if r:
                    sai = r[0] if lado > 0 else 1 / r[0]
            if sai is None and i == fim - 1:
                sai = c[i]
            pir = cf.get("piramide") or {}
            if sai is None and not peso and pir.get("max_unidades", 1) > pos["unidades"]:
                # PIRÂMIDE: andou a favor `a_cada` × a distância do stop original desde a última compra → soma mais uma unidade
                passo_p = pos["dist0"] * pir.get("a_cada", 1.0)
                if lado * (c[i] / pos["ultimo"] - 1) >= passo_p:
                    st_atual = pos["m"]["stop"] if lado > 0 else 1 / pos["m"]["stop"]
                    dist = abs(c[i] - st_atual) / c[i]
                    eq_m = pos["eq0"] + lado * N * (c[i] / px0 - 1) - pos["custos"]
                    j = dimensionar(eq_m, eq_m, c[i], dist, cfj, 1.0, True, pir.get("fracao", 0.5))
                    dN = j["notional"]
                    if dN > 0:
                        # preço médio ponderado (em notional): o lucro já acumulado fica guardado em "custos" negativos
                        ganho_ate_aqui = lado * N * (c[i] / px0 - 1)
                        pos["custos"] -= ganho_ate_aqui
                        pos["N"], pos["px"] = N * (c[i] / px0) + dN, c[i]
                        pos["custos"] += dN * taxa
                        pos["margem"] += j["margem"]
                        L = max(1, pos["N"] / pos["margem"])
                        pos["liq"] = c[i] * (1 - 1 / L + mmr) if lado > 0 else c[i] * (1 + 1 / L - mmr)
                        pos["unidades"] += 1
                        pos["ultimo"] = c[i]
            if sai is not None:
                if sai == "liq":
                    pnl = -pos["margem"] - pos["custos"]
                else:
                    pnl = lado * N * (sai / px0 - 1) - N * taxa * (sai / px0) - pos["custos"]
                trades.append(pnl / pos["eq0"])
                eq = max(0.0, pos["eq0"] + pnl)
                pos = None
        if not pos and i < fim - 1 and eq > 0.01:
            lado, fr, stop, m = 0, 1.0, None, None
            if peso:
                net = est.peso(d, v, i, p) - est.peso(de, ve, i, p)
                if abs(net) >= 0.1:
                    lado, fr = (1 if net > 0 else -1), abs(net)
                    a = d.get("atr", [None] * (i + 1))[i] if d.get("atr") else None
                    dist = p.get("stop_atr", 3.0) * a / c[i] if a else 0.08
                    stop = c[i] * (1 - dist) if lado > 0 else c[i] * (1 + dist)
            else:
                compra, venda = pode_entrar(est, d, v, i, p), pode_entrar(est, de, ve, i, p)
                if compra != venda:
                    lado = 1 if compra else -1
                    dd, vv = (d, v) if compra else (de, ve)
                    s_, a_ = niveis_de_entrada(dd, i, p, vv["c"][i])
                    m = {"preco": vv["c"][i], "stop": s_, "alvo": a_, "barras": 0, "maxc": vv["c"][i]}
                    stop = s_ if lado > 0 else 1 / s_
                    fr = fracao_entrada(dd, i, p)
            if lado:
                rg = reg[i]
                j = dimensionar(eq, eq, c[i], abs(c[i] - stop) / c[i], cfj, 1.0, rg == 0 or rg == lado, fr)
                N, L = j["notional"], j["alavancagem"]
                if N > 0:
                    liq = c[i] * (1 - 1 / L + mmr) if lado > 0 else c[i] * (1 + 1 / L - mmr)
                    pos = {"lado": lado, "N": N, "px": c[i], "eq0": eq, "margem": j["margem"], "liq": liq,
                           "stop": stop, "m": m, "custos": N * taxa, "unidades": 1, "ultimo": c[i],
                           "dist0": abs(c[i] - stop) / c[i]}
        if pos:
            marca = pos["eq0"] + pos["lado"] * pos["N"] * (c[i] / pos["px"] - 1) - pos["custos"]
            exp += pos["N"] / max(marca, 1e-9)
        else:
            marca = eq
        curva[t[i] // DIA] = marca
    return curva, trades, exp / max(fim - ini, 1)


def regime_alinhado(v, par, intervalo, filtro):
    """Para cada vela de v: +1/−1/0 pela média 50 × 200 das velas diárias JÁ FECHADAS."""
    d1 = _dados(par, filtro.get("intervalo", "1d"))
    if not d1["t"]:
        return [0] * len(v["t"])
    r, le = indicadores.ema(d1["c"], filtro["rapida"]), indicadores.ema(d1["c"], filtro["lenta"])
    passo = DIA // BARRAS_POR_DIA[intervalo]
    saida = []
    for tt in v["t"]:
        j = bisect.bisect_right(d1["t"], tt + passo - DIA) - 1
        saida.append(0 if j < 0 or r[j] is None or le[j] is None else (1 if r[j] > le[j] else -1))
    return saida


def _indices(v, t_ini, t_fim):
    return bisect.bisect_left(v["t"], t_ini), bisect.bisect_left(v["t"], t_fim)


def metricas(curva_lista, trades, exposicao=None):
    """curva_lista = patrimônio diário."""
    if len(curva_lista) < 2:
        return None
    ret = curva_lista[-1] / curva_lista[0] - 1
    anos = len(curva_lista) / 365
    pico, dd = curva_lista[0], 0.0
    for x in curva_lista:
        pico = max(pico, x)
        dd = min(dd, x / pico - 1)
    diarios = [curva_lista[k] / curva_lista[k - 1] - 1 for k in range(1, len(curva_lista))]
    media = statistics.fmean(diarios)
    dp = statistics.pstdev(diarios)
    sr = media / dp if dp > 0 else 0.0
    if dp > 0:
        assim = statistics.fmean([((r - media) / dp) ** 3 for r in diarios])
        curt = statistics.fmean([((r - media) / dp) ** 4 for r in diarios])
    else:
        assim, curt = 0.0, 3.0
    ganhos = sum(x for x in trades if x > 0)
    perdas = -sum(x for x in trades if x < 0)
    return {
        "retorno_pct": round(ret * 100, 2),
        "cagr_pct": round(((1 + ret) ** (1 / anos) - 1) * 100, 2) if anos > 0 and ret > -1 else -100.0,
        "max_dd_pct": round(dd * 100, 2),
        "sharpe": round(sr * math.sqrt(365), 2),
        "calmar": round((((1 + ret) ** (1 / anos) - 1) / -dd), 2) if dd < 0 and ret > -1 and anos > 0 else 0.0,
        "profit_factor": round(ganhos / perdas, 2) if perdas > 0 else (99.0 if ganhos > 0 else 0.0),
        "trades": len(trades),
        "acerto_pct": round(sum(1 for x in trades if x > 0) / len(trades) * 100, 1) if trades else 0.0,
        "exposicao_pct": None if exposicao is None else round(exposicao * 100, 1),
        "_sr_diario": sr, "_assimetria": assim, "_curtose": curt, "_dias": len(diarios),
    }


def _carteira(curvas):
    """Média igual das curvas diárias de cada par (cada uma começa em 1.0)."""
    dias = sorted(set().union(*[c.keys() for c in curvas]))
    ultimos = [1.0] * len(curvas)
    saida = []
    for dia in dias:
        for k, c in enumerate(curvas):
            if dia in c:
                ultimos[k] = c[dia]
        saida.append((dia, sum(ultimos) / len(ultimos)))
    return saida


def _normalizar(curva):
    if not curva:
        return {}
    primeiro = curva[min(curva)]
    return {k: x / primeiro for k, x in curva.items()}


# ---------------------------------------------------------------------------
_DADOS = {}


def _dados(par, intervalo, invertido=False):
    chave = (par, intervalo, invertido)
    if chave not in _DADOS:
        _DADOS[chave] = espelho(_dados(par, intervalo)) if invertido else historico.como_dicionario(historico.carregar(par, intervalo))
    return _DADOS[chave]


def estudar_aluno(est_id, cfg, fim_t):
    """Walk-forward completo de UMA estratégia (roda em paralelo, um processo por aluno)."""
    est = POR_ID[est_id]
    pares, taxa, derrap = cfg["pares"], cfg["taxa"], cfg["derrapagem"]
    fut = cfg.get("futuros") if cfg.get("mercado") == "futuros" else None
    combos = list(est.combinacoes())
    cache_ind, cache_reg = {}, {}

    def ind(par, p, invertido=False):
        chave = (par, json.dumps(p, sort_keys=True), invertido)
        if chave not in cache_ind:
            cache_ind[chave] = est.calcular(_dados(par, p["intervalo"], invertido), p)
        return cache_ind[chave]

    def reg(par, itv):
        if (par, itv) not in cache_reg:
            cache_reg[(par, itv)] = regime_alinhado(_dados(par, itv), par, itv, fut.get("regime", {"intervalo": "1d", "rapida": 50, "lenta": 200}))
        return cache_reg[(par, itv)]

    def rodar(p, t_ini, t_fim, custo=1.0):
        curvas, trades, exp = [], [], 0.0
        for par in pares:
            v = _dados(par, p["intervalo"])
            if not v["t"] or v["t"][0] > t_ini - 30 * DIA:
                return None  # falta histórico (precisa de folga pros indicadores)
            a, b = _indices(v, t_ini, t_fim)
            if fut:
                curva, tr, e = backtest_futuros(est, v, ind(par, p), _dados(par, p["intervalo"], True), ind(par, p, True),
                                                p, a, b, fut, reg(par, p["intervalo"]), custo)
            else:
                curva, tr, e = backtest(est, v, ind(par, p), p, a, b, taxa * custo, derrap * custo)
            curvas.append(_normalizar(curva))
            trades += tr
            exp += e / len(pares)
        return curvas, trades, exp

    def nota_treino(p, t_ini, t_fim):
        r = rodar(p, t_ini, t_fim)
        if r is None:
            return None
        curvas, trades, _ = r
        if len(trades) < 6:
            return -9.0
        m = metricas([x for _, x in _carteira(curvas)], trades)
        return m["sharpe"] if m else -9.0

    # vizinhos = combinações que diferem em UM só parâmetro
    vizinhos = [[j for j, q in enumerate(combos) if j != k and sum(p[x] != q[x] for x in p) == 1]
                for k, p in enumerate(combos)]

    def melhor(t_ini, t_fim):
        """Escolhe o "platô": a nota de cada combinação é metade dela mesma e metade a média dos
        vizinhos — assim não premiamos um pico isolado (que costuma ser sorte)."""
        brutas = [nota_treino(p, t_ini, t_fim) for p in combos]
        notas = []
        for k, n in enumerate(brutas):
            if n is None:
                continue
            viz = [brutas[j] for j in vizinhos[k] if brutas[j] is not None]
            notas.append((0.5 * n + 0.5 * (sum(viz) / len(viz)) if viz else n, k))
        return combos[max(notas)[1]] if notas else None

    tr_d, te_d, nprov = cfg["treino_dias"] * DIA, cfg["teste_dias"] * DIA, cfg["provas"]
    inicio_oos = fim_t - nprov * te_d
    oos = {1.0: [dict() for _ in pares], 2.0: [dict() for _ in pares]}
    nivel = {1.0: [1.0] * len(pares), 2.0: [1.0] * len(pares)}
    trades_oos, provas, exp_soma = [], [], 0.0
    for k in range(nprov):
        a = inicio_oos + k * te_d
        b = a + te_d
        p = melhor(a - tr_d, a)
        if p is None:
            continue
        for custo in (1.0, 2.0):
            curvas, trades, exp = rodar(p, a, b, custo)
            for j, c in enumerate(curvas):
                for dia in sorted(c):
                    oos[custo][j][dia] = nivel[custo][j] * c[dia]
                if c:
                    nivel[custo][j] = oos[custo][j][max(c)]
            if custo == 1.0:
                trades_oos += trades
                exp_soma += exp
                provas.append({"inicio": a, "fim": b, "params": p, "trades": len(trades),
                               "retorno_por_par_pct": [round((c[max(c)] - 1) * 100, 2) if c else 0.0 for c in curvas]})

    if not provas:
        return {"id": est_id, "erro": "sem histórico suficiente"}

    carteira = _carteira(oos[1.0])
    m = metricas([x for _, x in carteira], trades_oos, exp_soma / len(provas))
    dobrado = metricas([x for _, x in _carteira(oos[2.0])], [])
    positivos = sum(1 for pr in provas for r in pr["retorno_por_par_pct"] if r >= 0)  # "não perdeu dinheiro"
    total = sum(len(pr["retorno_por_par_pct"]) for pr in provas)
    atuais = melhor(fim_t - tr_d, fim_t) or est.params
    passo = max(1, len(carteira) // 240)
    return {
        "id": est.id, "nome": est.nome, "emoji": est.emoji, "inspiracao": est.inspiracao,
        "descricao": est.descricao, "par": "carteira " + "/".join(p[:-4] for p in pares), "intervalo": atuais["intervalo"],
        "oos": dict(m, consistencia_pct=round(positivos / total * 100, 1) if total else 0.0,
                    provas_positivas=positivos, provas=total,
                    retorno_custo_dobrado_pct=dobrado["retorno_pct"] if dobrado else None),
        "por_par_pct": {par: round((oos[1.0][j][max(oos[1.0][j])] - 1) * 100, 2) if oos[1.0][j] else 0.0
                        for j, par in enumerate(pares)},
        "provas": provas, "params_atuais": atuais, "combinacoes_testadas": len(combos),
        "curva": [[dia * DIA, round(x, 4)] for dia, x in carteira[::passo]],
        "_diaria": carteira, "_trades": trades_oos,
    }


def referencias(cfg, fim_t):
    """Comprar e segurar a carteira, e DCA semanal, no mesmo período das provas."""
    inicio = fim_t - cfg["provas"] * cfg["teste_dias"] * DIA
    curvas_bh, curvas_dca = [], []
    for par in cfg["pares"]:
        v = _dados(par, "1d")
        a, b = _indices(v, inicio, fim_t)
        curvas_bh.append({v["t"][i] // DIA: v["c"][i] / v["c"][a] for i in range(a, b)})
        # DCA: o mesmo dinheiro dividido em aportes semanais iguais
        semanas = list(range(a, b, 7))
        cota = 1.0 / len(semanas)
        unidades, caixa, curva = 0.0, 1.0, {}
        for i in range(a, b):
            if i in semanas:
                unidades += cota * (1 - cfg["taxa"]) / v["c"][i]
                caixa -= cota
            curva[v["t"][i] // DIA] = caixa + unidades * v["c"][i]
        curvas_dca.append(curva)
    saida = {}
    for nome, curvas in (("segurar", curvas_bh), ("dca", curvas_dca)):
        carteira = _carteira(curvas)
        m = metricas([x for _, x in carteira], [])
        passo = max(1, len(carteira) // 240)
        saida[nome] = dict({k: x for k, x in m.items() if not k.startswith("_")},
                           curva=[[dia * DIA, round(x, 4)] for dia, x in carteira[::passo]])
    return saida


def deflated_sharpe(resultados):
    """Probabilidade de o Sharpe ser real e não sorte, dado quantos alunos foram testados
    (Bailey & López de Prado, 2014)."""
    nd = statistics.NormalDist()
    srs = [r["oos"]["_sr_diario"] for r in resultados]
    n = len(srs)
    if n < 2:
        return
    var = statistics.pvariance(srs)
    gama = 0.5772156649
    sr0 = math.sqrt(var) * ((1 - gama) * nd.inv_cdf(1 - 1 / n) + gama * nd.inv_cdf(1 - 1 / (n * math.e)))
    for r in resultados:
        o = r["oos"]
        sr, t, g3, g4 = o["_sr_diario"], o["_dias"], o["_assimetria"], o["_curtose"]
        den = 1 - g3 * sr + (g4 - 1) / 4 * sr * sr
        z = (sr - sr0) * math.sqrt(max(t - 1, 1)) / math.sqrt(den) if den > 0 else 0.0
        o["dsr"] = round(nd.cdf(z), 3)


def dar_nota(r, cfg):
    o = r["oos"]
    ap = cfg["aprovacao"]
    nota = max(0.0, min(10.0, o["sharpe"] * 5))
    nota *= 0.4 + 0.6 * (o["consistencia_pct"] / 100)
    nota *= min(1.0, o["trades"] / ap["trades_min"])
    nota *= 0.5 + 0.5 * o.get("dsr", 0)
    if o["max_dd_pct"] < ap["queda_max_pct"]:
        nota *= 0.6
    motivos = []
    if o["retorno_pct"] <= 0:
        motivos.append("perdeu dinheiro fora da amostra")
    if o["retorno_custo_dobrado_pct"] is not None and o["retorno_custo_dobrado_pct"] <= 0:
        motivos.append("não aguenta custo dobrado")
    if o["sharpe"] < ap["sharpe_min"]:
        motivos.append(f"risco/retorno (Sharpe {o['sharpe']}) abaixo de {ap['sharpe_min']}")
    if o["profit_factor"] < ap["profit_factor_min"]:
        motivos.append(f"ganhos/perdas (PF {o['profit_factor']}) abaixo de {ap['profit_factor_min']}")
    if o["trades"] < ap["trades_min"]:
        motivos.append(f"poucas operações ({o['trades']}) pra confiar")
    if o["consistencia_pct"] < ap["consistencia_min"] * 100:
        motivos.append(f"inconsistente: perdeu dinheiro em {100 - o['consistencia_pct']:.0f}% das provas")
    if o["max_dd_pct"] < ap["queda_max_pct"]:
        motivos.append(f"queda máxima de {o['max_dd_pct']:.0f}%")
    if o.get("dsr", 0) < ap["dsr_min"]:
        motivos.append(f"pode ser sorte (confiança {o.get('dsr', 0) * 100:.0f}% < {ap['dsr_min'] * 100:.0f}%)")
    r["nota"] = round(nota, 1)
    r["aprovada"] = not motivos
    r["motivos"] = motivos
    return r


def comite(resultados, n=3):
    """As N melhores dividindo o dinheiro em partes iguais (fora da amostra, mesmo período)."""
    membros = [r for r in resultados if r.get("_diaria")][:n]
    if len(membros) < 2:
        return None
    curvas = [{dia: x for dia, x in r["_diaria"]} for r in membros]
    carteira = _carteira(curvas)
    trades = [x / len(membros) for r in membros for x in r["_trades"]]
    m = metricas([x for _, x in carteira], trades)
    if not m:
        return None
    oos = {k: x for k, x in m.items() if not k.startswith("_")}
    oos["dsr"] = round(sum(r["oos"].get("dsr", 0) for r in membros) / len(membros), 3)
    passo = max(1, len(carteira) // 240)
    return {"membros": [r["id"] for r in membros], "nomes": [f"{r['emoji']} {r['nome']}" for r in membros], "oos": oos,
            "nota": round(sum(r["nota"] for r in membros) / len(membros), 1),
            "curva": [[dia * DIA, round(x, 4)] for dia, x in carteira[::passo]]}


def rodar_escola(cfg_usuario=None, avisar=print, paralelo=True, futuros=None):
    cfg = json.loads(json.dumps(PADRAO))
    cfg.update(cfg_usuario or {})
    if futuros and futuros.get("ativo"):
        cfg["mercado"], cfg["futuros"] = "futuros", futuros
        cfg["taxa"], cfg["derrapagem"] = futuros.get("taxa_taker", 0.0005), futuros.get("derrapagem", 0.0002)
    else:
        cfg["mercado"] = "spot"
    intervalos = sorted({p["intervalo"] for e in TODAS for p in e.combinacoes()} | {"1d"})
    avisar("📚 Atualizando o histórico de preços (na primeira vez pode demorar uns minutos)...")
    for itv in intervalos:
        for par in cfg["pares"]:
            historico.atualizar(par, itv, avisar)

    fim_t = (int(time.time() * 1000) // DIA) * DIA
    avisar(f"🎓 {len(TODAS)} alunos fazendo {cfg['provas']} provas de {cfg['teste_dias']} dias cada "
           f"(estudam os {cfg['treino_dias']} dias anteriores a cada prova)...")
    inicio = time.time()
    resultados = []
    if paralelo:
        try:
            with ProcessPoolExecutor(max_workers=max(1, (os.cpu_count() or 2) - 1)) as ex:
                futuros = [(ex.submit(estudar_aluno, e.id, cfg, fim_t), e) for e in TODAS]
                for f, e in futuros:
                    resultados.append(f.result())
                    avisar(f"   {e.emoji} {e.nome}: provas corrigidas")
        except Exception as erro:
            avisar(f"   (sem processamento paralelo, vou um por um: {erro})")
            resultados, paralelo = [], False
    if not paralelo:
        for e in TODAS:
            resultados.append(estudar_aluno(e.id, cfg, fim_t))
            avisar(f"   {e.emoji} {e.nome}: provas corrigidas")

    resultados = [r for r in resultados if "erro" not in r]
    deflated_sharpe(resultados)
    resultados = [dar_nota(r, cfg) for r in resultados]
    resultados.sort(key=lambda r: (r["aprovada"], r["nota"], r["oos"]["sharpe"]), reverse=True)
    refs = referencias(cfg, fim_t)
    com = comite(resultados, (cfg_usuario or {}).get("comite_membros", 3))
    for r in resultados:
        r["oos"] = {k: x for k, x in r["oos"].items() if not k.startswith("_")}
        r["oos"]["buy_hold_pct"] = refs["segurar"]["retorno_pct"]
        r.pop("_diaria", None)
        r.pop("_trades", None)
    saida = {
        "gerado_em": int(time.time() * 1000), "duracao_s": round(time.time() - inicio),
        "config": cfg, "periodo_oos": [fim_t - cfg["provas"] * cfg["teste_dias"] * DIA, fim_t],
        "alunos_testados": len(resultados),
        "combinacoes_testadas": sum(r["combinacoes_testadas"] for r in resultados),
        "referencias": refs, "resultados": resultados, "mercado": cfg["mercado"], "comite": com,
    }
    ARQ_ESCOLA.parent.mkdir(exist_ok=True)
    ARQ_ESCOLA.write_text(json.dumps(saida, ensure_ascii=False), encoding="utf-8")
    return saida


def carregar():
    if ARQ_ESCOLA.exists():
        return json.loads(ARQ_ESCOLA.read_text(encoding="utf-8"))
    return None


def campea(escola):
    """A melhor aluna APROVADA (ou None)."""
    if not escola:
        return None
    return next((r for r in escola["resultados"] if r["aprovada"]), None)
