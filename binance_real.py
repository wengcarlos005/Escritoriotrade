"""Conector da conta de FUTUROS (USDT-M) da Binance — só o necessário pra agência operar.

  • Testnet (dinheiro de mentira, plataforma de verdade): https://testnet.binancefuture.com
  • Real: https://fapi.binance.com
  • Assinatura HMAC-SHA256 das ordens, como a Binance exige. Só biblioteca padrão do Python.

A chave fica em dados/binance.json (nunca vai pro GitHub nem pra nuvem). Use uma chave SEM permissão de saque.
"""
import hashlib
import hmac
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
ARQ_CHAVE = AQUI / "dados" / "binance.json"
BASES = {"testnet": "https://testnet.binancefuture.com", "real": "https://fapi.binance.com"}


class ErroBinance(Exception):
    def __init__(self, codigo, msg):
        super().__init__(f"Binance {codigo}: {msg}")
        self.codigo, self.msg = codigo, msg


def assinar(segredo, consulta):
    return hmac.new(segredo.encode("utf-8"), consulta.encode("utf-8"), hashlib.sha256).hexdigest()


def carregar_chave():
    try:
        return json.loads(ARQ_CHAVE.read_text(encoding="utf-8"))
    except Exception:
        return None


def salvar_chave(modo, chave, segredo):
    ARQ_CHAVE.parent.mkdir(exist_ok=True)
    ARQ_CHAVE.write_text(json.dumps({"modo": modo, "chave": chave.strip(), "segredo": segredo.strip()}), encoding="utf-8")
    try:
        ARQ_CHAVE.chmod(0o600)
    except Exception:
        pass


class Cliente:
    def __init__(self, modo, chave=None, segredo=None, timeout=20):
        if modo not in BASES:
            raise ValueError("modo tem que ser 'testnet' ou 'real'")
        self.modo, self.base, self.chave, self.segredo, self.timeout = modo, BASES[modo], chave, segredo, timeout
        self._delta = 0          # diferença entre o relógio do PC e o da Binance
        self._regras = None

    # ---------------- HTTP ----------------
    def _req(self, metodo, caminho, params=None, assinado=False):
        params = dict(params or {})
        if assinado:
            if not (self.chave and self.segredo):
                raise ErroBinance(-1, "falta a chave da API (rode o 9_conectar_binance.bat)")
            params["timestamp"] = int(time.time() * 1000) + self._delta
            params.setdefault("recvWindow", 10000)
        consulta = urllib.parse.urlencode(params)
        if assinado:
            consulta += "&signature=" + assinar(self.segredo, consulta)
        url = f"{self.base}{caminho}" + (f"?{consulta}" if consulta else "")
        cab = {"User-Agent": "agencia-de-trade/1.0"}
        if self.chave:
            cab["X-MBX-APIKEY"] = self.chave
        req = urllib.request.Request(url, method=metodo, headers=cab, data=b"" if metodo in ("POST", "DELETE") else None)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                corpo = json.loads(e.read().decode("utf-8"))
                raise ErroBinance(corpo.get("code", e.code), corpo.get("msg", str(e)))
            except (ValueError, KeyError):
                raise ErroBinance(e.code, str(e))

    def sincronizar_relogio(self):
        srv = self._req("GET", "/fapi/v1/time")["serverTime"]
        self._delta = srv - int(time.time() * 1000)
        return self._delta

    # ---------------- público ----------------
    def regras(self):
        """Tamanho mínimo, passo de quantidade e de preço de cada moeda."""
        if self._regras is None:
            info = self._req("GET", "/fapi/v1/exchangeInfo")
            r = {}
            for s in info["symbols"]:
                f = {x["filterType"]: x for x in s["filters"]}
                r[s["symbol"]] = {"passo": float((f.get("MARKET_LOT_SIZE") or f["LOT_SIZE"])["stepSize"]),
                                  "min_qtd": float((f.get("MARKET_LOT_SIZE") or f["LOT_SIZE"])["minQty"]),
                                  "max_qtd": float((f.get("MARKET_LOT_SIZE") or f["LOT_SIZE"])["maxQty"]),
                                  "min_notional": float((f.get("MIN_NOTIONAL") or {}).get("notional", 5)),
                                  "tick": float((f.get("PRICE_FILTER") or {}).get("tickSize", 0.01))}
            self._regras = r
        return self._regras

    def preco(self, par):
        return float(self._req("GET", "/fapi/v1/ticker/price", {"symbol": par})["price"])

    # ---------------- conta (assinado) ----------------
    def conta(self):
        """Patrimônio (com o lucro/prejuízo em aberto) e posições por moeda."""
        a = self._req("GET", "/fapi/v2/account", assinado=True)
        pos = {p["symbol"]: float(p["positionAmt"]) for p in a.get("positions", []) if float(p.get("positionAmt", 0)) != 0}
        return {"patrimonio": float(a["totalMarginBalance"]), "carteira": float(a["totalWalletBalance"]),
                "disponivel": float(a["availableBalance"]), "em_aberto": float(a["totalUnrealizedProfit"]), "posicoes": pos}

    def preparar_moeda(self, par, alavancagem):
        """Margem cruzada e alavancagem máxima permitida na moeda (a exposição de verdade quem decide é a agência)."""
        try:
            self._req("POST", "/fapi/v1/marginType", {"symbol": par, "marginType": "CROSSED"}, assinado=True)
        except ErroBinance as e:
            if e.codigo != -4046:   # "não precisa mudar"
                raise
        self._req("POST", "/fapi/v1/leverage", {"symbol": par, "leverage": int(alavancagem)}, assinado=True)

    def modo_unico(self):
        """Garante o modo de posição única (one-way): uma posição líquida por moeda."""
        r = self._req("GET", "/fapi/v1/positionSide/dual", assinado=True)
        if r.get("dualSidePosition"):
            self._req("POST", "/fapi/v1/positionSide/dual", {"dualSidePosition": "false"}, assinado=True)

    def stops_abertos(self, par):
        """Stops de emergência da agência abertos nessa moeda: [(id, preço)]."""
        ordens = self._req("GET", "/fapi/v1/openOrders", {"symbol": par}, assinado=True)
        return [(o["orderId"], float(o["stopPrice"])) for o in ordens if o.get("type") == "STOP_MARKET" and str(o.get("clientOrderId", "")).startswith("agencia-sos")]

    def cancelar(self, par, ident):
        self._req("DELETE", "/fapi/v1/order", {"symbol": par, "orderId": ident}, assinado=True)

    def stop_emergencia(self, par, lado_posicao, preco_stop):
        """Ordem que fica NA BINANCE (funciona com o PC desligado): fecha a posição inteira se o preço chegar lá."""
        tick = self.regras()[par].get("tick", 0.01)
        return self._req("POST", "/fapi/v1/order", {"symbol": par, "side": "SELL" if lado_posicao > 0 else "BUY", "type": "STOP_MARKET",
                                                    "stopPrice": _fmt_preco(preco_stop, tick), "closePosition": "true",
                                                    "workingType": "MARK_PRICE", "newClientOrderId": f"agencia-sos-{int(time.time())}"[:36]},
                         assinado=True)

    def ordem_mercado(self, par, quantidade, reduzir=False, ident=None):
        """quantidade > 0 compra, < 0 vende."""
        params = {"symbol": par, "side": "BUY" if quantidade > 0 else "SELL", "type": "MARKET",
                  "quantity": _fmt_qtd(abs(quantidade), self.regras()[par]["passo"])}
        if reduzir:
            params["reduceOnly"] = "true"
        if ident:
            params["newClientOrderId"] = ident[:36]
        return self._req("POST", "/fapi/v1/order", params, assinado=True)


def _fmt_preco(preco, tick):
    casas = max(0, -int(math.floor(math.log10(tick)))) if tick < 1 else 0
    return f"{math.floor(preco / tick + 1e-9) * tick:.{casas}f}"


def arredondar(qtd, passo):
    """Arredonda PRA BAIXO no passo da moeda (nunca manda mais do que o calculado)."""
    if passo <= 0:
        return qtd
    n = math.floor(abs(qtd) / passo + 1e-9)
    return math.copysign(round(n * passo, 12), qtd) if n else 0.0


def _fmt_qtd(qtd, passo):
    casas = max(0, -int(math.floor(math.log10(passo)))) if passo < 1 else 0
    return f"{arredondar(qtd, passo):.{casas}f}"
