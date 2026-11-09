"""Busca preços na Binance (dados públicos, sem chave de API e sem dinheiro envolvido)."""
import json
import time
import urllib.parse
import urllib.request

# Endpoint público de dados de mercado da Binance (só leitura).
BASE = "https://data-api.binance.vision/api/v3"
# Futuros perpétuos USDT-M (dados públicos). Em alguns países/redes é bloqueado: aí usamos o à vista.
FAPI = "https://fapi.binance.com/fapi/v1"
_FONTE = {"futuros": False, "falhas": 0}

INTERVALOS_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
}


def _get(caminho, params, tentativas=4, base=None):
    url = f"{base or BASE}/{caminho}?{urllib.parse.urlencode(params)}"
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "agencia-de-trade/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            if i == tentativas - 1:
                raise
            time.sleep(2 ** i)


def _vela(k):
    return {"t": k[0], "o": float(k[1]), "h": float(k[2]), "l": float(k[3]),
            "c": float(k[4]), "v": float(k[5]), "fim": k[6]}


def usar_futuros(ativo=True):
    """Tenta os dados de FUTUROS de verdade (preço do contrato perpétuo e funding). Devolve True se deu certo."""
    _FONTE["futuros"], _FONTE["falhas"] = False, 0
    if not ativo:
        return False
    try:
        _get("premiumIndex", {"symbol": "BTCUSDT"}, tentativas=2, base=FAPI)
        _FONTE["futuros"] = True
    except Exception:
        pass
    return _FONTE["futuros"]


def fonte():
    return "futuros" if _FONTE["futuros"] else "spot"


def _tentar_futuros(caminho, params):
    """Chama a API de futuros; se falhar 3 vezes seguidas, volta pro à vista até a próxima vez que ligar."""
    try:
        r = _get(caminho, params, tentativas=2, base=FAPI)
        _FONTE["falhas"] = 0
        return r
    except Exception:
        _FONTE["falhas"] += 1
        if _FONTE["falhas"] >= 3:
            _FONTE["futuros"] = False
        return None


def velas(par, intervalo, limite=500, inicio=None):
    params = {"symbol": par, "interval": intervalo, "limit": limite}
    if inicio is not None:
        params["startTime"] = int(inicio)
    if _FONTE["futuros"]:
        r = _tentar_futuros("klines", params)
        if r is not None:
            return [_vela(k) for k in r]
    return [_vela(k) for k in _get("klines", params)]


def velas_desde(par, intervalo, inicio_ms):
    """Todas as velas JÁ FECHADAS a partir de inicio_ms (busca em lotes de 1000)."""
    passo = INTERVALOS_MS[intervalo]
    agora = int(time.time() * 1000)
    todas = []
    while inicio_ms < agora:
        lote = velas(par, intervalo, 1000, inicio_ms)
        if not lote:
            break
        todas.extend(lote)
        inicio_ms = lote[-1]["t"] + passo
        if len(lote) < 1000:
            break
    return [v for v in todas if v["fim"] < agora]


def ultimas_velas(par, intervalo, quantidade=300):
    """As últimas velas já fechadas."""
    agora = int(time.time() * 1000)
    return [v for v in velas(par, intervalo, quantidade + 1) if v["fim"] < agora][-quantidade:]


def historico(par, intervalo, dias):
    agora = int(time.time() * 1000)
    return velas_desde(par, intervalo, agora - dias * 86_400_000)


def precos(pares):
    """Preço atual de vários pares de uma vez: {'BTCUSDT': 75900.1, ...}."""
    if _FONTE["futuros"]:
        r = _tentar_futuros("ticker/price", {})
        if r is not None:
            quero = set(pares)
            achou = {x["symbol"]: float(x["price"]) for x in r if x.get("symbol") in quero}
            if len(achou) == len(quero):
                return achou
    lista = json.dumps(sorted(set(pares)), separators=(",", ":"))
    return {x["symbol"]: float(x["price"]) for x in _get("ticker/price", {"symbols": lista})}


def funding(pares):
    """Taxa de funding atual (a cada 8h) de cada contrato perpétuo: {'BTCUSDT': 0.0001, ...}. {} se não der."""
    if not _FONTE["futuros"]:
        return {}
    r = _tentar_futuros("premiumIndex", {})
    if not r:
        return {}
    quero = set(pares)
    return {x["symbol"]: float(x["lastFundingRate"]) for x in r if x.get("symbol") in quero and x.get("lastFundingRate") not in (None, "")}


def cotacao_brl():
    """Quantos reais vale 1 dólar (USDT). Devolve None se falhar."""
    try:
        return float(_get("ticker/price", {"symbol": "USDTBRL"})["price"])
    except Exception:
        return None
