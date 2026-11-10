"""Modelo de CHANCE DE WIN (velas de 5 min).

Quando a estratégia do trader não dá sinal, ele é obrigado a abrir uma operação mesmo assim: no lado
(LONG ou SHORT) que este modelo diz ter MAIOR chance de terminar ganhando.

Como funciona (simples e transparente, sem bibliotecas):
  • Olha 9 sinais do preço agora (retornos de 5 min, 30 min, 1h e 4h, distância das médias, RSI,
    volatilidade e a tendência das velas de 4h), todos medidos em "ATRs" pra valer pra qualquer moeda.
  • Duas regressões logísticas (uma pro LONG, outra pro SHORT) aprendem, com o histórico, a chance de
    o alvo (k × ATR a favor) chegar antes do stop (k × ATR contra) em até 2 horas, já descontando as taxas.
  • Ao vivo, a cada vela que completa 2 horas o modelo descobre o que teria acontecido e APRENDE com isso.
"""
import math

import indicadores

H = 24            # 2 horas em velas de 5 min
NOMES = ["ret_5m", "ret_30m", "ret_1h", "ret_4h", "dist_media20", "media20_vs_50", "rsi", "volatilidade", "tendencia_4h"]


def _clip(x, a=3.0):
    return max(-a, min(a, x))


def preparar(v):
    """Indicadores que o modelo usa (calcule uma vez por buffer)."""
    c = v["c"]
    return {"atr": indicadores.atr(v["h"], v["l"], c, 14), "atr100": indicadores.atr(v["h"], v["l"], c, 100),
            "e20": indicadores.ema(c, 20), "e50": indicadores.ema(c, 50), "rsi": indicadores.rsi(c, 14)}


def sinais(v, ind, i, tend4h=0):
    """Vetor de sinais na vela i (ou None se ainda falta histórico)."""
    c = v["c"]
    if i < 50:
        return None
    a, a100, e20, e50, rsi = ind["atr"][i], ind["atr100"][i], ind["e20"][i], ind["e50"][i], ind["rsi"][i]
    if None in (a, a100, e20, e50, rsi) or a <= 0 or c[i] <= 0:
        return None
    ap = a / c[i]

    def ret(n):
        return _clip((c[i] / c[i - n] - 1) / ap / math.sqrt(n))
    return [ret(1), ret(6), ret(12), ret(48), _clip((c[i] - e20) / a), _clip((e20 - e50) / a),
            _clip((rsi - 50) / 25), _clip(a / a100 - 1), float(tend4h)]


def resultado(v, ind, i, lado, k_alvo, k_stop, custo, h=H):
    """1 se a operação aberta no fechamento da vela i (lado +1/−1) teria ganho, 0 se perdido, None se ainda não dá pra saber."""
    c, hi, lo = v["c"], v["h"], v["l"]
    n = len(c)
    if i + 1 >= n or ind["atr"][i] is None:
        return None
    p0, a = c[i], ind["atr"][i]
    alvo = p0 + lado * k_alvo * a
    stop = p0 - lado * k_stop * a
    for j in range(i + 1, min(n, i + 1 + h)):
        bateu_stop = lo[j] <= stop if lado > 0 else hi[j] >= stop
        bateu_alvo = hi[j] >= alvo if lado > 0 else lo[j] <= alvo
        if bateu_stop:            # se os dois na mesma vela, conta como stop (conservador)
            return 0
        if bateu_alvo:
            return 1
    if i + h >= n:
        return None
    final = lado * (c[i + h] / p0 - 1) - custo
    return 1 if final > 0 else 0


class Logistica:
    def __init__(self, n=len(NOMES), pesos=None):
        self.w = list(pesos) if pesos else [0.0] * (n + 1)   # último = viés

    def chance(self, x):
        z = self.w[-1] + sum(wi * xi for wi, xi in zip(self.w, x))
        return 1 / (1 + math.exp(-max(-30, min(30, z))))

    def aprender(self, x, y, taxa=0.01, l2=1e-4):
        erro = self.chance(x) - y
        for k, xi in enumerate(x):
            self.w[k] -= taxa * (erro * xi + l2 * self.w[k])
        self.w[-1] -= taxa * erro

    def treinar(self, amostras, epocas=3, taxa=0.02):
        for e in range(epocas):
            t = taxa / (1 + e)
            for x, y in amostras:
                self.aprender(x, y, t)
        return self


class ModeloChance:
    """Par de regressões (LONG e SHORT) + o placar de quanto ele tem acertado."""

    def __init__(self, d=None):
        d = d or {}
        self.long = Logistica(pesos=d.get("long"))
        self.short = Logistica(pesos=d.get("short"))
        self.vistos = d.get("vistos", 0)
        self.acertos = d.get("acertos", 0)

    def para_dict(self):
        return {"long": [round(x, 5) for x in self.long.w], "short": [round(x, 5) for x in self.short.w],
                "vistos": self.vistos, "acertos": self.acertos, "nomes": NOMES}

    def chances(self, x):
        return self.long.chance(x), self.short.chance(x)

    def melhor_lado(self, x):
        pl, ps = self.chances(x)
        return (1, pl, ps) if pl >= ps else (-1, ps, pl)

    def aprender(self, x, y_long, y_short, taxa=0.005):
        """Aprende com uma vela cujo resultado de 2 horas já é conhecido."""
        lado, p, _ = self.melhor_lado(x)
        y = y_long if lado > 0 else y_short
        if y is not None:
            self.vistos += 1
            self.acertos += int(y == 1)
        if y_long is not None:
            self.long.aprender(x, y_long, taxa)
        if y_short is not None:
            self.short.aprender(x, y_short, taxa)

    def explicar(self, x, lado):
        """Os 2 sinais que mais empurraram a chance pro lado escolhido (pra fala do trader)."""
        w = (self.long if lado > 0 else self.short).w
        contrib = sorted(((w[k] * x[k], NOMES[k]) for k in range(len(x))), reverse=True)
        return [n for c, n in contrib[:2] if c > 0]


NOME_SINAL = {"ret_5m": "a última vela", "ret_30m": "a última meia hora", "ret_1h": "a última hora", "ret_4h": "as últimas 4h",
              "dist_media20": "a distância da média de 20", "media20_vs_50": "a média 20 × 50", "rsi": "o RSI",
              "volatilidade": "a volatilidade", "tendencia_4h": "a tendência de 4h"}


def tendencias_4h(v5, v4, filtro=(20, 150)):
    """Tendência das velas de 4h (só fechadas) alinhada a cada vela de 5 min."""
    import bisect
    r, le = indicadores.ema(v4["c"], filtro[0]), indicadores.ema(v4["c"], filtro[1])
    saida = []
    for t in v5["t"]:
        j = bisect.bisect_right(v4["t"], t + 300_000 - 4 * 3_600_000) - 1
        saida.append(0 if j < 0 or r[j] is None or le[j] is None else (1 if r[j] > le[j] else -1))
    return saida


def treinar_do_historico(pares, k_alvo, k_stop, custo, carregar, dias_teste=30, passo=3, avisar=print, so_treino=False):
    """Treina o modelo com o histórico de 5 min e mede, nos últimos `dias_teste` dias (que ele NÃO viu),
    quantas vezes o lado escolhido teria ganhado. Depois retreina com tudo pra usar ao vivo."""
    import random
    por_par = {}
    for par in pares:
        v5, v4 = carregar(par, "5m"), carregar(par, "4h")
        if len(v5["t"]) < 2000 or not v4["t"]:
            continue
        ind, tg = preparar(v5), tendencias_4h(v5, v4)
        lista = []
        for i in range(60, len(v5["c"]) - H, passo):
            x = sinais(v5, ind, i, tg[i])
            if x is None:
                continue
            lista.append((v5["t"][i], x, resultado(v5, ind, i, 1, k_alvo, k_stop, custo), resultado(v5, ind, i, -1, k_alvo, k_stop, custo)))
        por_par[par] = lista
    if not por_par:
        return None, {}
    corte = max(l[-1][0] for l in por_par.values() if l) - dias_teste * 86_400_000
    treino = [a for l in por_par.values() for a in l if a[0] < corte]
    teste = [a for l in por_par.values() for a in l if a[0] >= corte]
    random.seed(7)

    def fit(amostras):
        random.shuffle(amostras)
        m = ModeloChance()
        m.long.treinar([(x, yl) for _, x, yl, ys in amostras if yl is not None])
        m.short.treinar([(x, ys) for _, x, yl, ys in amostras if ys is not None])
        return m
    m = fit(list(treino))
    acertos = total = base = 0
    for _, x, yl, ys in teste:
        lado = m.melhor_lado(x)[0]
        y = yl if lado > 0 else ys
        if y is None or yl is None or ys is None:
            continue
        total += 1
        acertos += y
        base += (yl + ys) / 2
    stats = {"amostras_treino": len(treino), "amostras_teste": total, "dias_teste": dias_teste,
             "acerto_modelo_pct": round(acertos / total * 100, 1) if total else None,
             "acerto_ao_acaso_pct": round(base / total * 100, 1) if total else None}
    final = m if so_treino else fit(treino + teste)
    return final, stats
