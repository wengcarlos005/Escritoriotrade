"""Sistema direcional (DMI/ADX) de J. Welles Wilder."""
from estrategias import Estrategia, _ok, cruzou_pra_baixo, cruzou_pra_cima


def _dmi(h, l, c, n):
    tam = len(c)
    pdi, mdi, adx = [None] * tam, [None] * tam, [None] * tam
    if tam <= 2 * n + 1:
        return pdi, mdi, adx
    s_tr = s_p = s_m = 0.0
    dxs, a = [], None
    for i in range(1, tam):
        up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
        p_ = up if up > dn and up > 0 else 0.0
        m_ = dn if dn > up and dn > 0 else 0.0
        tr = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        if i <= n:
            s_tr, s_p, s_m = s_tr + tr, s_p + p_, s_m + m_
            continue
        s_tr, s_p, s_m = s_tr - s_tr / n + tr, s_p - s_p / n + p_, s_m - s_m / n + m_
        pdi[i] = 100 * s_p / s_tr if s_tr else 0.0
        mdi[i] = 100 * s_m / s_tr if s_tr else 0.0
        dx = 100 * abs(pdi[i] - mdi[i]) / (pdi[i] + mdi[i]) if pdi[i] + mdi[i] else 0.0
        dxs.append(dx)
        if len(dxs) == n:
            a = sum(dxs) / n
        elif len(dxs) > n:
            a = (a * (n - 1) + dx) / n
        adx[i] = a
    return pdi, mdi, adx


class DMIWilder(Estrategia):
    id, nome, emoji = "dmi_wilder", "Movimento Direcional (ADX)", "🧮"
    inspiracao = "J. Welles Wilder"
    descricao = "Compra quando a força compradora (+DI) cruza acima da vendedora (−DI) com tendência forte (ADX acima do limite); sai quando cruza de volta."
    params = {"intervalo": "4h", "n": 14, "limite": 20, "stop_atr": 3.0}
    grade = {"intervalo": ["4h", "1d"], "n": [14, 28], "limite": [20, 25]}

    def indicadores(self, v, p):
        pdi, mdi, adx = _dmi(v["h"], v["l"], v["c"], p["n"])
        return {"pdi": pdi, "mdi": mdi, "adx": adx}

    def entrada(self, d, v, i, p):
        return cruzou_pra_cima(d["pdi"], d["mdi"], i) and _ok(d["adx"][i]) and d["adx"][i] >= p["limite"]

    def saida(self, d, v, i, p):
        return cruzou_pra_baixo(d["pdi"], d["mdi"], i)
