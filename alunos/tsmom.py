"""Momentum de série temporal (Moskowitz, Ooi & Pedersen, 2012 — usado por fundos como AQR e Man AHL)."""
from estrategias import Estrategia, _ok


class TSMOM(Estrategia):
    id, nome, emoji = "tsmom", "Virada do Momentum (AQR)", "🔄"
    inspiracao = "Moskowitz, Ooi & Pedersen (AQR)"
    descricao = "Fica do lado do retorno recente: compra quando o retorno das últimas N velas vira positivo e sai quando vira negativo."
    params = {"intervalo": "4h", "n": 120, "stop_atr": 3.0}
    grade = {"intervalo": ["4h", "1d"], "n": [60, 120, 240, 360]}

    def indicadores(self, v, p):
        c, n = v["c"], p["n"]
        return {"ret": [None] * min(n, len(c)) + [c[i] / c[i - n] - 1 for i in range(n, len(c))]}

    def entrada(self, d, v, i, p):
        r = d["ret"]
        return i >= 1 and _ok(r[i - 1], r[i]) and r[i - 1] <= 0 < r[i]

    def saida(self, d, v, i, p):
        return _ok(d["ret"][i]) and d["ret"][i] < 0

    def gatilho(self, d, v, i, p):
        return f"o retorno das últimas {p['n']} velas virar positivo" if _ok(d["ret"][i]) else None
