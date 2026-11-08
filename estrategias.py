"""Os alunos da Escola de Traders: cada um é uma estratégia inspirada num trader famoso.

Todas são long-only (só compram e vendem, sem operar vendido), como no spot da Binance.
Toda operação tem stop. As regras gerais de saída (stop, alvo, stop móvel, tempo máximo)
ficam em `checar_saida`, usada igualzinho no backtest da escola e na simulação ao vivo.
"""
import itertools
import math

import indicadores as ind_

BARRAS_POR_DIA = {"5m": 288, "15m": 96, "1h": 24, "4h": 6, "1d": 1}


def volatilidade_anual(c, intervalo, dias=20):
    """Volatilidade realizada anualizada (desvio dos retornos log nos últimos `dias`)."""
    bpd = BARRAS_POR_DIA[intervalo]
    n = dias * bpd
    rets = [0.0] + [math.log(c[i] / c[i - 1]) if c[i - 1] > 0 else 0.0 for i in range(1, len(c))]
    dp = ind_.desvio(rets, n)
    fator = math.sqrt(365 * bpd)
    return [None if x is None else x * fator for x in dp]


def _ok(*vals):
    return all(v is not None for v in vals)


def cruzou_pra_cima(a, b, i):
    return _ok(a[i - 1], b[i - 1], a[i], b[i]) and a[i - 1] <= b[i - 1] and a[i] > b[i]


def cruzou_pra_baixo(a, b, i):
    return _ok(a[i - 1], b[i - 1], a[i], b[i]) and a[i - 1] >= b[i - 1] and a[i] < b[i]


def _f(x):
    return f"{x:,.2f}" if x >= 1 else f"{x:.4f}"


class Estrategia:
    id = ""
    nome = ""
    emoji = ""
    inspiracao = ""
    descricao = ""
    tipo = "sinal"  # "sinal" (entra/sai) ou "peso" (diz quanto % do caixa ficar comprado)
    params = {}   # valores padrão (inclui "intervalo")
    grade = {}    # parâmetro -> lista de valores que a escola testa

    def combinacoes(self):
        chaves = list(self.grade)
        for valores in itertools.product(*(self.grade[k] for k in chaves)):
            p = dict(self.params)
            p.update(dict(zip(chaves, valores)))
            if self.valida(p):
                yield p

    def valida(self, p):
        return True

    def calcular(self, v, p):
        """v = colunas {'t','o','h','l','c','v'}. Devolve dicionário de indicadores."""
        d = {"atr": ind_.atr(v["h"], v["l"], v["c"], 14)}
        if p.get("vol_alvo"):
            d["vol"] = volatilidade_anual(v["c"], p["intervalo"])
        d.update(self.indicadores(v, p))
        return d

    def indicadores(self, v, p):
        return {}

    def peso(self, d, v, i, p):
        return 0.0

    def gatilho(self, d, v, i, p):
        """Frase curta: o que precisa acontecer pra este aluno comprar."""
        return None

    def distancia(self, d, v, i, p):
        """Quanto (%) o preço precisa subir pra este aluno comprar. None = não dá pra medir."""
        return None

    def entrada(self, d, v, i, p):
        return False

    def saida(self, d, v, i, p):
        return False


# ---------------------------------------------------------------------------
class Cruzamento(Estrategia):
    id, nome, emoji = "cruzamento", "Cruzamento de Médias", "🤖"
    inspiracao = "A estratégia original da agência"
    descricao = "Compra quando a média rápida cruza a lenta pra cima, com o preço acima da média de tendência e RSI abaixo de 70."
    params = {"intervalo": "1h", "rapida": 9, "lenta": 21, "tendencia": 100, "rsi_max": 70,
              "stop_atr": 1.5, "alvo_atr": 3.0, "max_barras": 32}
    grade = {"intervalo": ["1h", "4h"], "rapida": [9, 20], "lenta": [21, 50]}

    def valida(self, p):
        return p["rapida"] < p["lenta"]

    def indicadores(self, v, p):
        c = v["c"]
        return {"r": ind_.ema(c, p["rapida"]), "l": ind_.ema(c, p["lenta"]),
                "t": ind_.ema(c, p["tendencia"]), "rsi": ind_.rsi(c, 14)}

    def entrada(self, d, v, i, p):
        return (cruzou_pra_cima(d["r"], d["l"], i) and _ok(d["t"][i], d["rsi"][i])
                and v["c"][i] > d["t"][i] and d["rsi"][i] < p["rsi_max"])


class Tartaruga(Estrategia):
    id, nome, emoji = "tartaruga", "Tartarugas (Donchian)", "🐢"
    inspiracao = "Richard Dennis e as Tartarugas"
    descricao = "Compra quando o preço rompe a máxima dos últimos N períodos; sai quando perde a mínima dos últimos M. Stop de 2 ATR."
    params = {"intervalo": "4h", "entrada_n": 20, "saida_n": 10, "stop_atr": 2.0}
    grade = {"intervalo": ["4h", "1d"], "entrada_n": [20, 55], "saida_n": [10, 20]}

    def valida(self, p):
        return p["saida_n"] < p["entrada_n"]

    def indicadores(self, v, p):
        return {"max": ind_.maxima_anterior(v["h"], p["entrada_n"]), "min": ind_.minima_anterior(v["l"], p["saida_n"])}

    def entrada(self, d, v, i, p):
        return _ok(d["max"][i]) and v["c"][i] > d["max"][i]

    def saida(self, d, v, i, p):
        return _ok(d["min"][i]) and v["c"][i] < d["min"][i]


    def gatilho(self, d, v, i, p):
        return f"fechar acima de {_f(d['max'][i])} (máxima de {p['entrada_n']} velas)" if _ok(d["max"][i]) else None

    def distancia(self, d, v, i, p):
        return (d["max"][i] / v["c"][i] - 1) * 100 if _ok(d["max"][i]) else None

class Seykota(Estrategia):
    id, nome, emoji = "seykota", "Médias Exponenciais Longas", "📈"
    inspiracao = "Ed Seykota"
    descricao = "Segue a tendência: entra quando a média exponencial rápida cruza a lenta pra cima e fica até cruzar pra baixo."
    params = {"intervalo": "1d", "rapida": 15, "lenta": 150, "stop_atr": 3.0}
    grade = {"intervalo": ["4h", "1d"], "rapida": [10, 15, 20, 50], "lenta": [100, 150, 200]}

    def valida(self, p):
        return p["lenta"] >= 3 * p["rapida"]

    def indicadores(self, v, p):
        return {"r": ind_.ema(v["c"], p["rapida"]), "l": ind_.ema(v["c"], p["lenta"])}

    def entrada(self, d, v, i, p):
        return cruzou_pra_cima(d["r"], d["l"], i)

    def saida(self, d, v, i, p):
        return cruzou_pra_baixo(d["r"], d["l"], i)


    def gatilho(self, d, v, i, p):
        if not _ok(d["r"][i], d["l"][i]):
            return None
        if d["r"][i] < d["l"][i]:
            return f"média {p['rapida']} ({_f(d['r'][i])}) cruzar pra cima da média {p['lenta']} ({_f(d['l'][i])})"
        return "a tendência esfriar e virar de novo (já está acima — espera o próximo cruzamento)"

    def distancia(self, d, v, i, p):
        if not _ok(d["r"][i], d["l"][i]) or d["r"][i] >= d["l"][i]:
            return None
        return (d["l"][i] / d["r"][i] - 1) * 100

class PTJ200(Estrategia):
    id, nome, emoji = "ptj200", "Acima da Média de 200", "🎩"
    inspiracao = "Paul Tudor Jones"
    descricao = "\"Nada de bom acontece abaixo da média de 200.\" Compra quando o preço passa pra cima da média longa e sai quando volta pra baixo."
    params = {"intervalo": "1d", "n": 200, "banda": 0.02, "stop_atr": 4.0}
    grade = {"intervalo": ["4h", "1d"], "n": [100, 150, 200], "banda": [0.0, 0.02, 0.04]}

    def indicadores(self, v, p):
        return {"m": ind_.sma(v["c"], p["n"])}

    def entrada(self, d, v, i, p):
        m, c, b = d["m"], v["c"], p["banda"]
        return _ok(m[i - 1], m[i]) and c[i - 1] <= m[i - 1] * (1 + b) and c[i] > m[i] * (1 + b)

    def saida(self, d, v, i, p):
        return _ok(d["m"][i]) and v["c"][i] < d["m"][i] * (1 - p["banda"])


    def gatilho(self, d, v, i, p):
        return f"fechar acima de {_f(d['m'][i] * (1 + p['banda']))} (média de {p['n']})" if _ok(d["m"][i]) else None

    def distancia(self, d, v, i, p):
        return (d["m"][i] * (1 + p["banda"]) / v["c"][i] - 1) * 100 if _ok(d["m"][i]) else None

class ConnorsRSI2(Estrategia):
    id, nome, emoji = "connors", "RSI(2) Reversão", "🎯"
    inspiracao = "Larry Connors"
    descricao = "Em tendência de alta (acima da média de 200), compra quedas fortes de curto prazo (RSI de 2 períodos muito baixo) e vende no repique, acima da média de 5."
    params = {"intervalo": "1d", "limite": 10, "stop_atr": 3.0, "max_barras": 10}
    grade = {"intervalo": ["1h", "4h", "1d"], "limite": [5, 10, 15]}

    def indicadores(self, v, p):
        c = v["c"]
        return {"rsi": ind_.rsi(c, 2), "m200": ind_.sma(c, 200), "m5": ind_.sma(c, 5)}

    def entrada(self, d, v, i, p):
        return _ok(d["rsi"][i], d["m200"][i]) and v["c"][i] > d["m200"][i] and d["rsi"][i] < p["limite"]

    def saida(self, d, v, i, p):
        return _ok(d["m5"][i]) and v["c"][i] > d["m5"][i]


    def gatilho(self, d, v, i, p):
        if _ok(d["m200"][i]) and v["c"][i] < d["m200"][i]:
            return f"voltar acima da média de 200 ({_f(d['m200'][i])}) e ter uma queda forte"
        return f"uma queda forte de curto prazo (RSI(2) abaixo de {p['limite']})"

class BollingerReversao(Estrategia):
    id, nome, emoji = "bollinger", "Bandas de Bollinger", "🪃"
    inspiracao = "John Bollinger"
    descricao = "Em tendência de alta, compra quando o preço fecha abaixo da banda de baixo e vende quando volta pra média do meio."
    params = {"intervalo": "4h", "k": 2.0, "stop_atr": 2.5, "max_barras": 30}
    grade = {"intervalo": ["1h", "4h"], "k": [2.0, 2.5]}

    def indicadores(self, v, p):
        c = v["c"]
        m, s = ind_.sma(c, 20), ind_.desvio(c, 20)
        return {"m": m, "inf": [None if a is None else a - p["k"] * b for a, b in zip(m, s)], "m200": ind_.sma(c, 200)}

    def entrada(self, d, v, i, p):
        return _ok(d["inf"][i], d["m200"][i]) and v["c"][i] < d["inf"][i] and v["c"][i] > d["m200"][i]

    def saida(self, d, v, i, p):
        return _ok(d["m"][i]) and v["c"][i] > d["m"][i]


class Squeeze(Estrategia):
    id, nome, emoji = "squeeze", "Aperto e Explosão", "💥"
    inspiracao = "John Bollinger / John Carter (squeeze)"
    descricao = "Espera as bandas ficarem bem apertadas (mercado parado) e compra quando o preço explode pra cima. Sai com stop móvel."
    params = {"intervalo": "4h", "fator": 0.8, "stop_atr": 2.0, "trail_atr": 2.5}
    grade = {"intervalo": ["1h", "4h"], "fator": [0.7, 0.9], "trail_atr": [2.0, 3.0]}

    def indicadores(self, v, p):
        c = v["c"]
        m, s = ind_.sma(c, 20), ind_.desvio(c, 20)
        sup = [None if a is None else a + 2 * b for a, b in zip(m, s)]
        larg = [None if a is None or a == 0 else 4 * b / a for a, b in zip(m, s)]
        validos = [x for x in larg if x is not None]
        lm = [None] * (len(larg) - len(validos)) + ind_.sma(validos, 100)
        return {"sup": sup, "larg": larg, "lm": lm}

    def entrada(self, d, v, i, p):
        return (_ok(d["sup"][i], d["larg"][i - 1], d["lm"][i - 1])
                and d["larg"][i - 1] < d["lm"][i - 1] * p["fator"] and v["c"][i] > d["sup"][i])


class Williams(Estrategia):
    id, nome, emoji = "williams", "Rompimento de Volatilidade", "🚀"
    inspiracao = "Larry Williams"
    descricao = "Compra quando o preço sobe mais que uma fração (k) da amplitude do período anterior, a favor da tendência. Fica poucos períodos."
    params = {"intervalo": "1d", "k": 0.6, "stop_atr": 1.5, "max_barras": 3}
    grade = {"intervalo": ["4h", "1d"], "k": [0.3, 0.5, 0.7], "max_barras": [1, 3]}

    def indicadores(self, v, p):
        return {"m": ind_.sma(v["c"], 50)}

    def entrada(self, d, v, i, p):
        rng = v["h"][i - 1] - v["l"][i - 1]
        return _ok(d["m"][i]) and v["c"][i] > v["o"][i] + p["k"] * rng and v["c"][i] > d["m"][i]


    def gatilho(self, d, v, i, p):
        return f"subir mais de {p['k']:.0%} da amplitude da vela anterior, acima da média de 50"

class MACD(Estrategia):
    id, nome, emoji = "macd", "MACD", "🌊"
    inspiracao = "Gerald Appel"
    descricao = "Compra quando a linha do MACD cruza a linha de sinal pra cima, com o preço acima da média de 200; sai no cruzamento pra baixo."
    params = {"intervalo": "4h", "stop_atr": 2.5}
    grade = {"intervalo": ["1h", "4h", "1d"]}

    def indicadores(self, v, p):
        linha, sinal = ind_.macd(v["c"])
        return {"macd": linha, "sinal": sinal, "e200": ind_.ema(v["c"], 200)}

    def entrada(self, d, v, i, p):
        return cruzou_pra_cima(d["macd"], d["sinal"], i) and _ok(d["e200"][i]) and v["c"][i] > d["e200"][i]

    def saida(self, d, v, i, p):
        return cruzou_pra_baixo(d["macd"], d["sinal"], i)


class Supertrend(Estrategia):
    id, nome, emoji = "supertrend", "Supertrend", "🦸"
    inspiracao = "Olivier Seban"
    descricao = "Usa uma linha que acompanha a volatilidade (ATR): compra quando a tendência vira pra cima e vende quando vira pra baixo."
    params = {"intervalo": "4h", "mult": 3.0, "stop_atr": 3.0}
    grade = {"intervalo": ["1h", "4h", "1d"], "mult": [2.0, 3.0]}

    def indicadores(self, v, p):
        return {"dir": ind_.supertrend(v["h"], v["l"], v["c"], 10, p["mult"])}

    def entrada(self, d, v, i, p):
        return d["dir"][i - 1] == -1 and d["dir"][i] == 1

    def saida(self, d, v, i, p):
        return d["dir"][i - 1] == 1 and d["dir"][i] == -1


    def gatilho(self, d, v, i, p):
        return "a linha do Supertrend virar pra alta"

class Momentum(Estrategia):
    id, nome, emoji = "momentum", "Momentum de Série Temporal", "🧭"
    inspiracao = "Moskowitz, Ooi & Pedersen (AQR)"
    descricao = "Se o preço subiu nos últimos N períodos, fica comprado; se caiu, fica de fora. Pode reduzir a aposta quando o mercado está nervoso (volatilidade alta)."
    params = {"intervalo": "1d", "n": 50, "stop_atr": 5.0, "vol_alvo": None}
    grade = {"intervalo": ["4h", "1d"], "n": [20, 50, 90], "vol_alvo": [None, 0.6]}

    def indicadores(self, v, p):
        return {"roc": ind_.roc(v["c"], p["n"])}

    def entrada(self, d, v, i, p):
        return _ok(d["roc"][i]) and d["roc"][i] > 0

    def saida(self, d, v, i, p):
        return _ok(d["roc"][i]) and d["roc"][i] < 0


    def gatilho(self, d, v, i, p):
        n = p["n"]
        return f"fechar acima de {_f(v['c'][i - n + 1])} (preço de {n} velas atrás)" if i >= n else None

    def distancia(self, d, v, i, p):
        n = p["n"]
        return (v["c"][i - n + 1] / v["c"][i] - 1) * 100 if i >= n else None

class Minervini(Estrategia):
    id, nome, emoji = "minervini", "Molde de Tendência", "🏆"
    inspiracao = "Mark Minervini / Stan Weinstein"
    descricao = "Só compra ativos em tendência forte (preço > MM50 > MM150 > MM200 subindo, perto da máxima de 1 ano) quando rompem a máxima de 20 períodos. Stop curto em %."
    params = {"intervalo": "1d", "stop_pct": 0.08}
    grade = {"intervalo": ["1d"], "stop_pct": [0.06, 0.08, 0.12]}

    def indicadores(self, v, p):
        c, h, l = v["c"], v["h"], v["l"]
        return {"m50": ind_.sma(c, 50), "m150": ind_.sma(c, 150), "m200": ind_.sma(c, 200),
                "max20": ind_.maxima_anterior(h, 20), "max252": ind_.maxima_anterior(h, 252),
                "min252": ind_.minima_anterior(l, 252)}

    def entrada(self, d, v, i, p):
        if i < 21 or not _ok(d["m50"][i], d["m150"][i], d["m200"][i], d["m200"][i - 20], d["max20"][i], d["max252"][i], d["min252"][i]):
            return False
        c = v["c"][i]
        return (c > d["m50"][i] > d["m150"][i] > d["m200"][i] and d["m200"][i] > d["m200"][i - 20]
                and c >= 1.3 * d["min252"][i] and c >= 0.75 * d["max252"][i] and c > d["max20"][i])

    def saida(self, d, v, i, p):
        return _ok(d["m50"][i]) and v["c"][i] < d["m50"][i]


    def gatilho(self, d, v, i, p):
        return "tendência forte (médias 50 > 150 > 200 subindo) e romper a máxima de 20 velas"

class Raschke(Estrategia):
    id, nome, emoji = "raschke", "Santo Graal", "🏹"
    inspiracao = "Linda Raschke"
    descricao = "Com tendência forte (ADX alto), espera o preço recuar até a média de 20 e compra quando ele volta a subir. Alvo e stop pela volatilidade."
    params = {"intervalo": "4h", "adx_min": 30, "stop_atr": 1.5, "alvo_atr": 3.0, "max_barras": 20}
    grade = {"intervalo": ["1h", "4h"], "adx_min": [25, 30], "alvo_atr": [2.0, 3.0]}

    def indicadores(self, v, p):
        return {"adx": ind_.adx(v["h"], v["l"], v["c"], 14), "e20": ind_.ema(v["c"], 20)}

    def entrada(self, d, v, i, p):
        a, e = d["adx"], d["e20"]
        return (_ok(a[i], a[i - 1], e[i]) and a[i] > p["adx_min"] and a[i] >= a[i - 1]
                and v["l"][i] <= e[i] < v["c"][i] and v["c"][i] > v["o"][i])


class Weinstein(Estrategia):
    id, nome, emoji = "weinstein", "Análise de Estágios", "🪜"
    inspiracao = "Stan Weinstein"
    descricao = "Compra no \"estágio 2\": preço acima da média de 30 semanas, com a média subindo. Sai quando o preço fecha abaixo dela."
    params = {"intervalo": "1d", "n": 210, "inclinacao": 20, "stop_atr": 4.0}
    grade = {"intervalo": ["1d"], "n": [140, 210, 280], "inclinacao": [10, 20]}

    def indicadores(self, v, p):
        return {"m": ind_.sma(v["c"], p["n"])}

    def _estagio2(self, d, v, i, p):
        m, k = d["m"], p["inclinacao"]
        return i >= k and _ok(m[i], m[i - k]) and m[i] > m[i - k] and v["c"][i] > m[i]

    def entrada(self, d, v, i, p):
        # entra quando o estágio 2 COMEÇA (não estava no estágio 2 na vela anterior)
        return self._estagio2(d, v, i, p) and not self._estagio2(d, v, i - 1, p)

    def saida(self, d, v, i, p):
        return _ok(d["m"][i]) and v["c"][i] < d["m"][i]


    def gatilho(self, d, v, i, p):
        m, k = d["m"], p["inclinacao"]
        if not _ok(m[i], m[i - k]):
            return None
        sobe = m[i] > m[i - k]
        if v["c"][i] > m[i] and not sobe:
            return f"a média de {p['n']} ({_f(m[i])}) virar pra cima"
        return f"fechar acima da média de {p['n']} ({_f(m[i])})" + ("" if sobe else " com ela subindo")

    def distancia(self, d, v, i, p):
        m = d["m"]
        if not _ok(m[i]) or v["c"][i] > m[i]:
            return None
        return (m[i] / v["c"][i] - 1) * 100

class DonchianConjunto(Estrategia):
    id, nome, emoji = "donchian_conjunto", "Conjunto de Canais", "🛰️"
    inspiracao = "Zarattini, Pagani & Barbon — \"Catching Crypto Trends\" (2025)"
    descricao = ("Vários sistemas de rompimento (Donchian) com prazos diferentes votam juntos: quanto mais "
                 "deles estão em tendência de alta, maior a posição — e a aposta diminui quando a volatilidade sobe.")
    tipo = "peso"
    CONJUNTOS = {"curto": [10, 20, 30, 60], "longo": [60, 90, 150, 250], "todos": [10, 20, 30, 60, 90, 150, 250]}
    params = {"intervalo": "1d", "conjunto": "todos", "vol_alvo": 0.6}
    grade = {"intervalo": ["1d"], "conjunto": ["curto", "longo", "todos"], "vol_alvo": [0.4, 0.6, 0.8]}

    def indicadores(self, v, p):
        c, h, l = v["c"], v["h"], v["l"]
        prazos = self.CONJUNTOS[p["conjunto"]]
        n = len(c)
        exposicao = [0.0] * n
        pronto = [False] * n
        for L in prazos:
            topo, fundo = ind_.maxima_anterior(h, L), ind_.minima_anterior(l, max(2, L // 2))
            dentro = False
            for i in range(n):
                if topo[i] is None or fundo[i] is None:
                    continue
                pronto[i] = True
                if not dentro and c[i] > topo[i]:
                    dentro = True
                elif dentro and c[i] < fundo[i]:
                    dentro = False
                if dentro:
                    exposicao[i] += 1 / len(prazos)
        return {"exp": [e if ok else None for e, ok in zip(exposicao, pronto)]}

    def peso(self, d, v, i, p):
        e = d["exp"][i]
        if e is None or e <= 0:
            return 0.0
        vol = d.get("vol", [None])[i] if d.get("vol") else None
        escala = min(1.0, p["vol_alvo"] / vol) if vol else 1.0
        return max(0.0, min(1.0, e * escala))




class Pullback(Estrategia):
    id, nome, emoji = "pullback", "Recuo na Tendência", "🎢"
    inspiracao = "Linda Raschke / Larry Connors (com filtro de tendência longa)"
    descricao = ("Opera velas de 1h, mas só quando a tendência de semanas está pra cima (preço acima da média de ~50 dias). "
                 "Compra quando o preço dá uma recuada forte de curto prazo (RSI de 2 bem baixo) e sai no repique.")
    params = {"intervalo": "1h", "longa": 1200, "limite": 10, "saida": "ema20", "stop_atr": 2.5, "max_barras": 24}
    grade = {"intervalo": ["1h"], "longa": [600, 1200], "limite": [5, 10, 20], "max_barras": [12, 24]}

    def indicadores(self, v, p):
        c = v["c"]
        return {"longa": ind_.sma(c, p["longa"]), "rsi": ind_.rsi(c, 2), "e20": ind_.ema(c, 20), "e50": ind_.ema(c, 50)}

    def entrada(self, d, v, i, p):
        return (_ok(d["longa"][i], d["rsi"][i], d["e50"][i]) and v["c"][i] > d["longa"][i]
                and v["c"][i] > d["e50"][i] * 0.98 and d["rsi"][i] < p["limite"])

    def saida(self, d, v, i, p):
        return _ok(d["e20"][i]) and v["c"][i] > d["e20"][i] and v["c"][i] > v["c"][i - 1]

    def gatilho(self, d, v, i, p):
        if _ok(d["longa"][i]) and v["c"][i] < d["longa"][i]:
            return f"voltar acima da média longa ({_f(d['longa'][i])}) e recuar forte"
        return f"uma recuada forte de curto prazo (RSI(2) abaixo de {p['limite']})"

    def distancia(self, d, v, i, p):
        return (d["longa"][i] / v["c"][i] - 1) * 100 if _ok(d["longa"][i]) and v["c"][i] < d["longa"][i] else None


class RompimentoFiltrado(Estrategia):
    id, nome, emoji = "rompimento_filtrado", "Rompimento com Filtro", "🧲"
    inspiracao = "Turtles / Darvas, com filtro de tendência longa"
    descricao = ("Velas de 1h: compra quando o preço rompe a máxima dos últimos 1–3 dias, mas só se a tendência de semanas "
                 "estiver pra cima. Sai com stop móvel que acompanha a alta.")
    params = {"intervalo": "1h", "longa": 1200, "entrada_n": 48, "stop_atr": 2.0, "trail_atr": 3.0}
    grade = {"intervalo": ["1h"], "longa": [600, 1200], "entrada_n": [24, 48, 72], "trail_atr": [2.5, 4.0]}

    def indicadores(self, v, p):
        return {"longa": ind_.sma(v["c"], p["longa"]), "max": ind_.maxima_anterior(v["h"], p["entrada_n"])}

    def entrada(self, d, v, i, p):
        return _ok(d["longa"][i], d["max"][i]) and v["c"][i] > d["longa"][i] and v["c"][i] > d["max"][i]

    def gatilho(self, d, v, i, p):
        if _ok(d["longa"][i]) and v["c"][i] < d["longa"][i]:
            return f"voltar acima da média longa ({_f(d['longa'][i])})"
        return f"fechar acima de {_f(d['max'][i])} (máxima de {p['entrada_n']} velas)" if _ok(d["max"][i]) else None

    def distancia(self, d, v, i, p):
        alvos = [x for x in (d["longa"][i], d["max"][i]) if x is not None]
        return (max(alvos) / v["c"][i] - 1) * 100 if alvos else None

def _gatilho_conjunto(self, d, v, i, p):
    return "o preço romper algum dos canais (máximas de " + ", ".join(str(x) for x in self.CONJUNTOS[p["conjunto"]]) + " velas)"


DonchianConjunto.gatilho = _gatilho_conjunto


def _distancia_conjunto(self, d, v, i, p):
    import indicadores as _i
    c = v["c"]
    alvos = [x for x in (_i.maxima_anterior(v["h"], L)[i] for L in self.CONJUNTOS[p["conjunto"]]) if x is not None]
    return (min(alvos) / c[i] - 1) * 100 if alvos else None


DonchianConjunto.distancia = _distancia_conjunto

TODAS = [DonchianConjunto(), Momentum(), Pullback(), RompimentoFiltrado(), Tartaruga(), Seykota(), PTJ200(), Weinstein(), Minervini(),
         Williams(), ConnorsRSI2(), Raschke(), Supertrend(), MACD(), Squeeze(), BollingerReversao(), Cruzamento()]
POR_ID = {e.id: e for e in TODAS}


# ---------------------------------------------------------------------------
# Execução: igual no backtest e ao vivo
def niveis_de_entrada(d, i, p, preco):
    """Stop e alvo iniciais de uma compra feita a `preco` no índice i."""
    a = d["atr"][i]
    if p.get("stop_pct"):
        stop = preco * (1 - p["stop_pct"])
    else:
        stop = preco - p.get("stop_atr", 2.0) * a
    alvo = preco + p["alvo_atr"] * a if p.get("alvo_atr") else None
    return stop, alvo


def checar_saida(est, d, v, i, p, pos):
    """Devolve (preço, motivo) se for pra sair na vela i; atualiza o stop móvel em pos."""
    o, h, l, c = v["o"][i], v["h"][i], v["l"][i], v["c"][i]
    pos["barras"] = pos.get("barras", 0) + 1
    if l <= pos["stop"]:
        return min(pos["stop"], o), ("stop móvel" if pos["stop"] > pos["preco"] else "stop")
    if pos.get("alvo") and h >= pos["alvo"]:
        return max(pos["alvo"], o), "alvo"
    if est.saida(d, v, i, p):
        return c, "sinal de saída"
    if p.get("max_barras") and pos["barras"] >= p["max_barras"]:
        return c, "tempo esgotado"
    if p.get("trail_atr") and d["atr"][i]:
        pos["maxc"] = max(pos.get("maxc", c), c)
        pos["stop"] = max(pos["stop"], pos["maxc"] - p["trail_atr"] * d["atr"][i])
    return None


def fracao_entrada(d, i, p):
    """Quanto do caixa usar numa compra: 100%, ou menos se a volatilidade estiver acima do alvo."""
    if p.get("vol_alvo") and d.get("vol") and d["vol"][i]:
        return max(0.05, min(1.0, p["vol_alvo"] / d["vol"][i]))
    return 1.0


def pode_entrar(est, d, v, i, p):
    return i >= 1 and d["atr"][i] is not None and est.entrada(d, v, i, p)
