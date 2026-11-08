"""Indicadores técnicos calculados sobre a série inteira (sem olhar o futuro).

Cada função recebe listas e devolve uma lista do mesmo tamanho; onde ainda não há dados
suficientes o valor é None.
"""
import math
from collections import deque


def sma(x, n):
    out = [None] * len(x)
    s = 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n:
            s -= x[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(x, n):
    out = [None] * len(x)
    k = 2 / (n + 1)
    e = None
    for i, v in enumerate(x):
        if i < n - 1:
            continue
        if e is None:
            e = sum(x[i - n + 1:i + 1]) / n
        else:
            e = v * k + e * (1 - k)
        out[i] = e
    return out


def desvio(x, n):
    out = [None] * len(x)
    s = s2 = 0.0
    for i, v in enumerate(x):
        s += v
        s2 += v * v
        if i >= n:
            s -= x[i - n]
            s2 -= x[i - n] ** 2
        if i >= n - 1:
            m = s / n
            out[i] = math.sqrt(max(s2 / n - m * m, 0.0))
    return out


def rsi(c, n):
    out = [None] * len(c)
    if len(c) <= n:
        return out
    g = p = 0.0
    for i in range(1, n + 1):
        d = c[i] - c[i - 1]
        g += max(d, 0)
        p += max(-d, 0)
    g /= n
    p /= n
    out[n] = 100.0 if p == 0 else 100 - 100 / (1 + g / p)
    for i in range(n + 1, len(c)):
        d = c[i] - c[i - 1]
        g = (g * (n - 1) + max(d, 0)) / n
        p = (p * (n - 1) + max(-d, 0)) / n
        out[i] = 100.0 if p == 0 else 100 - 100 / (1 + g / p)
    return out


def atr(h, l, c, n):
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    out = [None] * len(c)
    a = None
    for i, v in enumerate(tr):
        if i < n - 1:
            continue
        a = sum(tr[:n]) / n if a is None else (a * (n - 1) + v) / n
        out[i] = a
    return out


def maxima_anterior(x, n):
    """Máximo dos n valores ANTERIORES (não inclui o atual) — para rompimentos."""
    out = [None] * len(x)
    q = deque()
    for i in range(len(x)):
        if i >= n:
            out[i] = x[q[0]]
        # adiciona i
        while q and x[q[-1]] <= x[i]:
            q.pop()
        q.append(i)
        while q[0] <= i - n:
            q.popleft()
    return out


def minima_anterior(x, n):
    neg = maxima_anterior([-v for v in x], n)
    return [None if v is None else -v for v in neg]


def roc(c, n):
    return [None if i < n else c[i] / c[i - n] - 1 for i in range(len(c))]


def macd(c, rapida=12, lenta=26, sinal=9):
    er, el = ema(c, rapida), ema(c, lenta)
    linha = [None if a is None or b is None else a - b for a, b in zip(er, el)]
    validos = [v for v in linha if v is not None]
    s = ema(validos, sinal)
    sig = [None] * (len(linha) - len(validos)) + s
    return linha, sig


def supertrend(h, l, c, n=10, mult=3.0):
    """Devolve lista de direção: 1 (alta), -1 (baixa) ou None."""
    a = atr(h, l, c, n)
    dirc = [None] * len(c)
    sup = inf = None
    d = 1
    for i in range(len(c)):
        if a[i] is None:
            continue
        meio = (h[i] + l[i]) / 2
        bs, bi = meio + mult * a[i], meio - mult * a[i]
        if sup is None:
            sup, inf = bs, bi
        else:
            sup = bs if (bs < sup or c[i - 1] > sup) else sup
            inf = bi if (bi > inf or c[i - 1] < inf) else inf
        if d == 1 and c[i] < inf:
            d = -1
        elif d == -1 and c[i] > sup:
            d = 1
        dirc[i] = d
    return dirc


def adx(h, l, c, n=14):
    tam = len(c)
    out = [None] * tam
    if tam <= 2 * n:
        return out
    tr, pdm, mdm = [0.0], [0.0], [0.0]
    for i in range(1, tam):
        up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
        pdm.append(up if up > dn and up > 0 else 0.0)
        mdm.append(dn if dn > up and dn > 0 else 0.0)
        tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    s_tr, s_p, s_m = sum(tr[1:n + 1]), sum(pdm[1:n + 1]), sum(mdm[1:n + 1])
    dxs = []
    for i in range(n + 1, tam):
        s_tr = s_tr - s_tr / n + tr[i]
        s_p = s_p - s_p / n + pdm[i]
        s_m = s_m - s_m / n + mdm[i]
        pdi = 100 * s_p / s_tr if s_tr else 0
        mdi = 100 * s_m / s_tr if s_tr else 0
        dx = 100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi else 0
        dxs.append(dx)
        if len(dxs) == n:
            a = sum(dxs) / n
            out[i] = a
        elif len(dxs) > n:
            a = (a * (n - 1) + dx) / n
            out[i] = a
    return out
