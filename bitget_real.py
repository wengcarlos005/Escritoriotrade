"""Conector dos FUTUROS USDT-M (perpétuos) da BITGET — API V2 "mix", mesma interface do binance_real.

  • Real: https://api.bitget.com  (a Bitget não tem uma "testnet" separada simples: treine no modo PAPEL)
  • Assinatura: base64(HMAC-SHA256(segredo, timestamp + MÉTODO + caminho[?consulta] + corpo)) + a PASSPHRASE da chave.
  • Modo de posição única (one-way) e margem cruzada.
  • Stop de emergência: ordem "pos_loss" (stop loss da POSIÇÃO inteira, a mercado, pelo preço de marcação):
    fica na Bitget e funciona com o PC desligado.
A chave fica em dados/binance.json (nunca vai pro GitHub nem pra nuvem). Use uma chave SEM permissão de saque.
"""
import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from binance_real import ErroBinance, _fmt_preco, _fmt_qtd

BASE = "https://api.bitget.com"
PT = "USDT-FUTURES"
MOEDA = "USDT"


class Cliente:
    nome = "Bitget"

    def __init__(self, modo, chave=None, segredo=None, frase=None, timeout=20):
        if modo != "real":
            raise ValueError("na Bitget use o modo 'real' (pra treinar, use o modo papel)")
        self.modo, self.chave, self.segredo, self.frase, self.timeout = modo, chave, segredo, frase, timeout
        self._delta = 0
        self._regras = None

    # ---------------- HTTP ----------------
    def _req(self, metodo, caminho, params=None, assinado=False):
        params = dict(params or {})
        if metodo == "GET":
            consulta = "&".join(f"{k}={params[k]}" for k in sorted(params))
            alvo, corpo = caminho + (f"?{consulta}" if consulta else ""), ""
        else:
            alvo, corpo = caminho, json.dumps(params, separators=(",", ":"))
        cab = {"User-Agent": "agencia-de-trade/1.0", "Content-Type": "application/json", "locale": "en-US"}
        if assinado:
            if not (self.chave and self.segredo and self.frase):
                raise ErroBinance(-1, "falta a chave da API (rode o 9_conectar_binance.bat)")
            ts = str(int(time.time() * 1000) + self._delta)
            assinatura = base64.b64encode(hmac.new(self.segredo.encode(), (ts + metodo + alvo + corpo).encode(), hashlib.sha256).digest()).decode()
            cab.update({"ACCESS-KEY": self.chave, "ACCESS-SIGN": assinatura, "ACCESS-TIMESTAMP": ts, "ACCESS-PASSPHRASE": self.frase})
        req = urllib.request.Request(BASE + alvo, method=metodo, headers=cab, data=corpo.encode() if metodo != "GET" else None)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                d = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            texto = e.read().decode("utf-8", "replace")[:300]
            try:
                d = json.loads(texto)
            except ValueError:
                raise ErroBinance(e.code, "a Bitget bloqueou o acesso desta rede" if e.code == 403 else texto or str(e))
        if str(d.get("code", "00000")) != "00000":
            raise ErroBinance(d.get("code"), d.get("msg", "erro"))
        return d.get("data")

    def sincronizar_relogio(self):
        srv = int(self._req("GET", "/api/v2/public/time")["serverTime"])
        self._delta = srv - int(time.time() * 1000)
        return self._delta

    # ---------------- público ----------------
    def regras(self):
        if self._regras is None:
            r = {}
            for s in self._req("GET", "/api/v2/mix/market/contracts", {"productType": PT}) or []:
                casas = int(s.get("pricePlace") or 2)
                passo = float(s.get("sizeMultiplier") or 0) or 10 ** -int(s.get("volumePlace") or 3)
                r[s["symbol"]] = {"passo": passo, "min_qtd": float(s.get("minTradeNum") or passo),
                                  "max_qtd": float(s.get("maxMarketOrderQty") or 1e12), "min_notional": float(s.get("minTradeUSDT") or 5),
                                  "tick": float(s.get("priceEndStep") or 1) * 10 ** -casas}
            self._regras = r
        return self._regras

    def preco(self, par):
        d = self._req("GET", "/api/v2/mix/market/ticker", {"symbol": par, "productType": PT})
        d = d[0] if isinstance(d, list) else d
        return float(d.get("lastPr") or d.get("last"))

    # ---------------- conta (assinado) ----------------
    def conta(self):
        """Patrimônio (com o lucro/prejuízo em aberto) e posições por moeda (+ comprado, − vendido)."""
        contas = self._req("GET", "/api/v2/mix/account/accounts", {"productType": PT}, assinado=True) or []
        a = next((x for x in contas if x.get("marginCoin", "").upper() == MOEDA), contas[0] if contas else {})
        f = lambda *ks: next((float(a[k]) for k in ks if a.get(k) not in (None, "")), 0.0)
        pos = {}
        for p in self._req("GET", "/api/v2/mix/position/all-position", {"productType": PT, "marginCoin": MOEDA}, assinado=True) or []:
            q = float(p.get("total") or 0)
            if q:
                lado = -1 if p.get("holdSide") in ("short", "sell") else 1
                pos[p["symbol"]] = pos.get(p["symbol"], 0.0) + lado * q
        em_aberto = f("unrealizedPL", "crossedUnrealizedPL")
        patrimonio = f("accountEquity", "usdtEquity")
        return {"patrimonio": patrimonio, "carteira": patrimonio - em_aberto, "disponivel": f("crossedMaxAvailable", "available"),
                "em_aberto": em_aberto, "posicoes": pos}

    def preparar_moeda(self, par, alavancagem):
        base = {"symbol": par, "productType": PT, "marginCoin": MOEDA}
        try:
            self._req("POST", "/api/v2/mix/account/set-margin-mode", dict(base, marginMode="crossed"), assinado=True)
        except ErroBinance:
            pass   # já está cruzada (ou tem posição aberta: aí não dá pra mudar, e tudo bem)
        self._req("POST", "/api/v2/mix/account/set-leverage", dict(base, leverage=str(int(alavancagem))), assinado=True)

    def modo_unico(self):
        try:
            self._req("POST", "/api/v2/mix/account/set-position-mode", {"productType": PT, "posMode": "one_way_mode"}, assinado=True)
        except ErroBinance as e:
            if "position" not in str(e.msg).lower() and "mode" not in str(e.msg).lower():
                raise

    def stops_abertos(self, par):
        d = self._req("GET", "/api/v2/mix/order/orders-plan-pending", {"productType": PT, "planType": "profit_loss", "symbol": par}, assinado=True) or {}
        lista = d.get("entrustedList") if isinstance(d, dict) else d
        return [(o["orderId"], float(o.get("triggerPrice") or 0)) for o in (lista or [])
                if o.get("planType") == "pos_loss" and o.get("symbol", par) == par]

    def cancelar(self, par, ident):
        self._req("POST", "/api/v2/mix/order/cancel-plan-order", {"symbol": par, "productType": PT, "marginCoin": MOEDA,
                                                                 "orderId": str(ident), "planType": "pos_loss"}, assinado=True)

    def stop_emergencia(self, par, lado_posicao, preco_stop):
        """Fica NA BITGET (funciona com o PC desligado): fecha a posição inteira a mercado se o preço chegar lá."""
        return self._req("POST", "/api/v2/mix/order/place-tpsl-order", {
            "symbol": par, "productType": PT, "marginCoin": MOEDA, "planType": "pos_loss",
            "triggerPrice": _fmt_preco(preco_stop, self.regras()[par].get("tick", 0.01)), "triggerType": "mark_price",
            "holdSide": "buy" if lado_posicao > 0 else "sell"}, assinado=True)

    def ordem_mercado(self, par, quantidade, reduzir=False, ident=None):
        """quantidade > 0 compra, < 0 vende."""
        b = {"symbol": par, "productType": PT, "marginMode": "crossed", "marginCoin": MOEDA, "orderType": "market",
             "side": "buy" if quantidade > 0 else "sell", "size": _fmt_qtd(abs(quantidade), self.regras()[par]["passo"])}
        if reduzir:
            b["reduceOnly"] = "YES"
        if ident:
            b["clientOid"] = "".join(c for c in ident if c.isalnum() or c in "-_")[:40]
        r = self._req("POST", "/api/v2/mix/order/place-order", b, assinado=True) or {}
        return {"status": "enviada", "orderId": r.get("orderId"), "executedQty": b["size"], "avgPrice": None}
