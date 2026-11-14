"""PROVA DA AGÊNCIA: cada aluno da escola é testado do jeito que operaria no escritório de verdade.

  • 3 traders por aluno (BTC, ETH e SOL), no tamanho de vela da agência (4h no modo atual).
  • Walk-forward: em cada semestre, o aluno usa os parâmetros que a escola escolheu ANTES dele (nunca viu o futuro).
  • O tamanho segue as regras do escritório: mesmo risco pra cada trader (90 dias) e alavancagem pela volatilidade
    da carteira (60 dias), com teto. Taxas de entrada (limitada) e saída (a mercado + derrapagem) e funding.
  • O CAMPEÃO é a formação atual da agência (ex.: 3 times Seykota). Cada aluno é comparado sozinho e JUNTO com o
    campeão — a pergunta é: "ele melhora a agência?".

Só usa a biblioteca padrão do Python (roda em qualquer PC).
"""
import bisect
import json
import math
import os
import time
from pathlib import Path

import historico
from estrategias import POR_ID, checar_saida, niveis_de_entrada, pode_entrar
from motor_futuros import espelho

AQUI = Path(__file__).resolve().parent
ARQ = AQUI / "dados" / "escola_agencia.json"
DIA = 86_400_000
BR = 3 * 3_600_000   # dia no horário de Brasília
PASSO = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": DIA}

_DADOS = {}


def _velas(par, itv):
    if (par, itv) not in _DADOS:
        v = historico.como_dicionario(historico.carregar(par, itv))
        _DADOS[(par, itv)] = (v, espelho(v))
    return _DADOS[(par, itv)]


def sombra(est_id, par, itv, janelas, params_por_janela, custos):
    """Resultado diário (a 1x: posição = 100% do caixa) de UM trader, semestre a semestre. {dia: retorno}."""
    est = POR_ID[est_id]
    v, ve = _velas(par, itv)
    t, o, h, l, c = v["t"], v["o"], v["h"], v["l"], v["c"]
    ent, sai, fund = custos["entrada"], custos["saida"], custos["funding_8h"] * PASSO[itv] / (8 * 3_600_000)
    cache, out, n_ops = {}, {}, 0
    for (a, b), p in zip(janelas, params_por_janela):
        p = dict(p, intervalo=itv)
        chave = json.dumps(p, sort_keys=True)
        if chave not in cache:
            cache[chave] = (est.calcular(v, p), est.calcular(ve, p))
        d, de = cache[chave]
        i0, i1 = bisect.bisect_left(t, a), bisect.bisect_left(t, b)
        eq, pos, ult_dia, eq_dia_ant = 1.0, None, None, 1.0
        for i in range(max(i0, 60), i1):
            if pos:
                lado, px0 = pos["lado"], pos["px"]
                pos["fund"] += (c[i] / px0) * fund
                r = checar_saida(est, d if lado > 0 else de, v if lado > 0 else ve, i, p, pos["m"])
                saida = (r[0] if lado > 0 else 1 / r[0]) if r else (c[i] if i == i1 - 1 else None)
                if saida is not None:
                    eq = pos["eq0"] * (1 + lado * (saida / px0 - 1) - (saida / px0) * sai - ent - pos["fund"])
                    pos, n_ops = None, n_ops + 1
            if not pos and i < i1 - 1 and eq > 0.01:
                compra, venda = pode_entrar(est, d, v, i, p), pode_entrar(est, de, ve, i, p)
                if compra != venda:
                    lado = 1 if compra else -1
                    dd, vv = (d, v) if compra else (de, ve)
                    s_, a_ = niveis_de_entrada(dd, i, p, vv["c"][i])
                    pos = {"lado": lado, "px": c[i], "eq0": eq, "fund": 0.0,
                           "m": {"preco": vv["c"][i], "stop": s_, "alvo": a_, "barras": 0, "maxc": vv["c"][i]}}
            marca = pos["eq0"] * (1 + pos["lado"] * (c[i] / pos["px"] - 1) - ent - pos["fund"]) if pos else eq
            dia = (t[i] - BR) // DIA
            if ult_dia is not None and dia != ult_dia:
                out[ult_dia] = out.get(ult_dia, 0.0) + (marca_ant / eq_dia_ant - 1)
                eq_dia_ant = marca_ant
            ult_dia, marca_ant = dia, marca
        if ult_dia is not None:
            out[ult_dia] = out.get(ult_dia, 0.0) + (marca_ant / eq_dia_ant - 1)
    return out, n_ops


def _dp(xs):
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def carteira(series, dias, alvo, teto, jp=90, jv=60):
    """Junta os traders como o escritório faz: mesmo risco por trader + alavancagem pela volatilidade (só passado)."""
    nomes = list(series)
    R = {k: [series[k].get(d, 0.0) for d in dias] for k in nomes}
    port, final = [], []
    for j in range(len(dias)):
        vols = {k: _dp(R[k][max(0, j - jp):j]) for k in nomes} if j >= 20 else {}
        if vols and any(x > 0 for x in vols.values()):   # quem ainda não existia (moeda listada depois) fica com peso 0
            inv = {k: 1 / x for k, x in vols.items() if x > 0}
            s = sum(inv.values())
            w = {k: inv.get(k, 0.0) / s for k in nomes}
        else:
            w = {k: 1 / len(nomes) for k in nomes}
        port.append(sum(w[k] * R[k][j] for k in nomes))
        vp = _dp(port[max(0, j - jv):j]) * math.sqrt(365) if j >= 20 else 0.0
        lev = min(teto, alvo / vp) if vp > 0 else 1.0
        final.append(lev * port[-1])
    return final


def metricas(rets, dias, janelas):
    eq, pico, dd, curva = 1.0, 1.0, 0.0, []
    for r in rets:
        eq *= 1 + max(r, -0.95)
        pico = max(pico, eq)
        dd = min(dd, eq / pico - 1)
        curva.append(eq)
    anos = max(len(rets), 1) / 365
    cagr = eq ** (1 / anos) - 1 if eq > 0 else -1.0
    sharpe = (sum(rets) / len(rets)) / _dp(rets) * math.sqrt(365) if len(rets) > 1 and _dp(rets) > 0 else 0.0
    sem = []
    for a, b in janelas:
        da, db = (a - BR) // DIA, (b - BR) // DIA
        x = 1.0
        for d, r in zip(dias, rets):
            if da <= d < db:
                x *= 1 + max(r, -0.95)
        sem.append(round((x - 1) * 100, 1))
    return {"ao_ano_pct": round(cagr * 100, 1), "pior_queda_pct": round(dd * 100, 1), "sharpe": round(sharpe, 2),
            "semestres_pct": sem, "semestres_positivos": sum(1 for s in sem if s > 0), "total_pct": round((eq - 1) * 100, 1)}


def rodar(cfg, esc=None, avisar=print):
    import escola as escola_mod
    esc = esc or escola_mod.carregar()
    if not esc or not esc.get("resultados"):
        return None
    inicio = time.time()
    md, fut = cfg.get("modo", {}), cfg.get("futuros", {})
    cv = md.get("alavancagem_por_vol") or {}
    itv = md.get("intervalo_forcado") or "4h"
    alvo, teto = cv.get("risco_alvo", 0.6), cv.get("teto", 4.0)
    moedas = cfg.get("liga", {}).get("moedas") or ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    for par in moedas:   # moeda nova no escritório: baixa o histórico dela também
        try:
            historico.atualizar(par, itv, lambda *a, **k: None)
        except Exception:
            pass
    moedas = [m for m in moedas if len(historico.carregar(m, itv)) >= 500] or moedas[:3]
    custos = {"entrada": fut.get("taxa_maker", 0.0002) * (0.9 if fut.get("pagar_taxas_com_bnb") else 1),
              "saida": fut.get("taxa_taker", 0.0005) * (0.9 if fut.get("pagar_taxas_com_bnb") else 1) + fut.get("derrapagem", 0.0002),
              "funding_8h": fut.get("funding_8h", 0.00005)}
    agora = int(time.time() * 1000)
    ref = next((r for r in esc["resultados"] if r.get("provas")), None)
    janelas = [(pv["inicio"], min(pv["fim"], agora)) for pv in ref["provas"]]
    avisar(f"🏢 Prova da agência: cada aluno opera {', '.join(m.replace('USDT', '') for m in moedas)} em velas de {itv}, "
           f"com o tamanho do escritório (alvo de volatilidade {alvo * 100:.0f}%, teto {teto:g}x)...")

    # o CAMPEÃO = a formação atual (times fixos), ou os times que a escola escolheria
    fixos = cfg.get("liga", {}).get("times_fixos")
    por_id = {r["id"]: r for r in esc["resultados"]}
    if fixos:
        campeao = [(f["id"], f["estrategia"], [f["params"]] * len(janelas), f.get("nome") or f["id"]) for f in fixos]
    else:
        fora = set(cfg.get("liga", {}).get("estrategias_excluidas", []))
        top = [r for r in esc["resultados"] if r["id"] not in fora][:cfg.get("liga", {}).get("times", 3)]
        campeao = [(r["id"], r["id"], [pv["params"] for pv in r["provas"]], r["nome"]) for r in top]
    series_c = {}
    for tid, est_id, params, _ in campeao:
        for par in moedas:
            series_c[f"{tid}|{par}"], _n = sombra(est_id, par, itv, janelas, params, custos)

    def dias_de(*grupos):
        return sorted({d for g in grupos for s in g.values() for d in s})

    dias_c = dias_de(series_c)
    m_c = metricas(carteira(series_c, dias_c, alvo, teto), dias_c, janelas)
    alunos = []
    for r in esc["resultados"]:
        if not r.get("provas") or len(r["provas"]) != len(janelas) or r["id"] not in POR_ID:
            continue
        if POR_ID[r["id"]].tipo != "sinal":   # alunos de "peso" (dizem quanto ficar comprado) ainda não têm prova da agência
            continue
        params = [pv["params"] for pv in r["provas"]]
        try:
            series_a, ops = {}, 0
            for par in moedas:
                series_a[f"{r['id']}|{par}"], n = sombra(r["id"], par, itv, janelas, params, custos)
                ops += n
        except Exception as erro:
            avisar(f"   ⚠️ {r['nome']}: não consegui testar ({erro})")
            continue
        dias_a = dias_de(series_a)
        m_a = metricas(carteira(series_a, dias_a, alvo, teto), dias_a, janelas)
        juntos = dict(series_c, **series_a)
        dias_j = dias_de(juntos)
        m_j = metricas(carteira(juntos, dias_j, alvo, teto), dias_j, janelas)
        venceu = sum(1 for x, y in zip(m_a["semestres_pct"], m_c["semestres_pct"]) if x > y)
        ja_no_time = any(est_id == r["id"] for _, est_id, _, _ in campeao)
        if ja_no_time:
            veredito, texto = "⚽ no time", "Já faz parte da formação atual."
        elif m_a["sharpe"] >= m_c["sharpe"] + 0.15 and venceu >= math.ceil(len(janelas) * 0.6) and m_a["ao_ano_pct"] > m_c["ao_ano_pct"]:
            veredito, texto = "👑 pode virar campeão", f"Sozinho rendeu mais que a formação atual e venceu em {venceu} de {len(janelas)} semestres."
        elif m_j["sharpe"] >= m_c["sharpe"] + 0.10 and m_j["ao_ano_pct"] >= m_c["ao_ano_pct"]:
            veredito, texto = "🤝 reforça o time", (f"Junto com a formação atual, a agência ficaria mais estável (Sharpe {m_c['sharpe']:.2f} → "
                                                    f"{m_j['sharpe']:.2f}) sem perder retorno.")
        elif m_a["sharpe"] < 0.3:
            veredito, texto = "❌ não serve hoje", "Não tem vantagem suficiente depois das taxas, nem ajuda a diversificar."
        else:
            veredito, texto = "📖 continua estudando", "Não melhora a agência atual — fica na escola e é testado de novo toda semana."
        alunos.append({"id": r["id"], "nome": r["nome"], "emoji": r["emoji"], "inspiracao": r.get("inspiracao", ""),
                       "sozinho": m_a, "com_campeao": m_j, "operacoes": ops, "venceu_semestres": venceu,
                       "veredito": veredito, "texto": texto})
    ordem = {"👑 pode virar campeão": 0, "🤝 reforça o time": 1, "⚽ no time": 2, "📖 continua estudando": 3, "❌ não serve hoje": 4}
    alunos.sort(key=lambda a: (ordem.get(a["veredito"], 9), -a["sozinho"]["sharpe"]))
    saida = {"gerado_em": agora, "duracao_s": round(time.time() - inicio), "intervalo": itv, "moedas": moedas,
             "alvo_vol": alvo, "teto": teto, "janelas": janelas,
             "campeao": {"nome": " + ".join(n for _, _, _, n in campeao), **m_c}, "alunos": alunos}
    ARQ.parent.mkdir(exist_ok=True)
    tmp = ARQ.with_suffix(".tmp")
    tmp.write_text(json.dumps(saida, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, ARQ)
    cand = [a for a in alunos if a["veredito"].startswith(("👑", "🤝"))]
    avisar(f"   Campeão ({saida['campeao']['nome']}): {m_c['ao_ano_pct']:+.0f}% ao ano · pior queda {m_c['pior_queda_pct']:.0f}% · Sharpe {m_c['sharpe']:.2f}")
    for a in alunos[:8]:
        s = a["sozinho"]
        avisar(f"   {a['veredito']:<22} {a['emoji']} {a['nome']:<30} {s['ao_ano_pct']:+5.0f}%/ano · queda {s['pior_queda_pct']:4.0f}% · Sharpe {s['sharpe']:.2f}")
    avisar(f"   {len(cand)} candidato(s) a entrar no escritório." if cand else "   Nenhum aluno melhora a agência atual — o campeão continua.")
    return saida


def carregar():
    try:
        return json.loads(ARQ.read_text(encoding="utf-8")) if ARQ.exists() else None
    except Exception:
        return None
