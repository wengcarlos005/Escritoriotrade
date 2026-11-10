"""Ichimoku Kinko Hyo (Goichi Hosoda): tendência pela nuvem."""
from estrategias import Estrategia, _ok


def _meio(h, l, n):
    out = [None] * len(h)
    for i in range(n - 1, len(h)):
        out[i] = (max(h[i - n + 1:i + 1]) + min(l[i - n + 1:i + 1])) / 2
    return out


class Ichimoku(Estrategia):
    id, nome, emoji = "ichimoku", "Nuvem Ichimoku", "☁️"
    inspiracao = "Goichi Hosoda"
    descricao = "Compra quando o preço fecha acima da nuvem com a linha rápida (tenkan) acima da base (kijun); sai quando perde a base."
    params = {"intervalo": "4h", "t": 9, "k": 26, "s": 52, "stop_atr": 3.0}
    grade = {"intervalo": ["4h", "1d"], "t": [9, 20], "k": [26, 60], "s": [52, 120]}

    def valida(self, p):
        return p["t"] < p["k"] < p["s"]

    def indicadores(self, v, p):
        h, l = v["h"], v["l"]
        ten, kij, sb = _meio(h, l, p["t"]), _meio(h, l, p["k"]), _meio(h, l, p["s"])
        sa = [(a + b) / 2 if _ok(a, b) else None for a, b in zip(ten, kij)]
        k = p["k"]   # a nuvem de hoje foi desenhada k velas atrás (sem olhar o futuro)
        topo = [None] * len(h)
        for i in range(k, len(h)):
            if _ok(sa[i - k], sb[i - k]):
                topo[i] = max(sa[i - k], sb[i - k])
        return {"ten": ten, "kij": kij, "topo": topo}

    def entrada(self, d, v, i, p):
        c, topo = v["c"], d["topo"]
        return (i >= 1 and _ok(topo[i - 1], topo[i], d["ten"][i], d["kij"][i])
                and c[i - 1] <= topo[i - 1] and c[i] > topo[i] and d["ten"][i] > d["kij"][i])

    def saida(self, d, v, i, p):
        return _ok(d["kij"][i]) and v["c"][i] < d["kij"][i]
