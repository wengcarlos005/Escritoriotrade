"""Conector da conta de DERIVATIVOS (USDT perpétuo, categoria "linear") da BYBIT — mesma interface do binance_real.

  • Demo Trading (dinheiro de mentira, mesma plataforma): https://api-demo.bybit.com — a chave é criada no site
    normal da Bybit, com o modo "Demo Trading" ligado.
  • Real: https://api.bybit.com
  • Assinatura HMAC-SHA256 (API V5). Só biblioteca padrão do Python.

O stop de emergência aqui é o STOP LOSS DA POSIÇÃO (trading-stop, modo Full): fica na Bybit, fecha a posição inteira
a mercado se o preço de marcação chegar lá — funciona com o PC desligado.
A chave fica em dados/binance.json (nunca vai pro GitHub nem pra nuvem). Use uma chave SEM permissão de saque.
"""
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from binance_real import ErroBinance, _fmt_preco, _fmt_qtd

BASES = {"testnet": "https://api-demo.bybit.com", "real": "https://api.bybit.com"}
PUBLICO = "https://api.bybit.com"          # preços e regras: sempre os do mercado real
NAO_MUDOU = (110043, 110025, 34040)         # "não precisa mudar" (alavancagem, modo de posição, stop)


def _nao_mudou(e):
    return e.codigo in NAO_MUDOU or "not modified" in str(e.msg).lower()


class Cliente:
    nome = "Bybit"

    def __init__(self, modo, chave=None, segredo=None, timeout=20):
        if modo not in BASES:
            raise ValueError("modo tem que ser 'testnet' ou 'real'")
        self.modo, self.base, self.chave, self.segredo, self.timeout = modo, BASES[modo], chave, segredo, timeout
        self._delta = 0
        self._regras = None
        self.recv = 10000

    # ---------------- HTTP ----------------
    def _req(self, metodo, caminho, params=None, assinado=False, publico=False):
        params = dict(params or {})
        base = PUBLICO if publico else self.base
        cab = {"User-Agent": "agencia-de-trade/1.0"}
        if metodo == "GET":
            consulta = urllib.parse.urlencode(params)
            corpo, url = None, f"{base}{caminho}" + (f"?{consulta}" if consulta else "")
            assinar_isto = consulta
        else:
            corpo = json.dumps(params, separators=(",", ":"))
            url, assinar_isto = f"{base}{caminho}", corpo
            cab["Content-Type"] = "application/json"
        if assinado:
            if not (self.chave and self.segredo):
                raise ErroBinance(-1, "falta a chave da API (rode o 9_conectar_binance.bat)")
            ts = str(int(time.time() * 1000) + self._delta)
            texto = ts + self.chave + str(self.recv) + assinar_isto
            cab.update({"X-BAPI-API-KEY": self.chave, "X-BAPI-TIMESTAMP": ts, "X-BAPI-RECV-WINDOW": str(self.recv),
                        "X-BAPI-SIGN": hmac.new(self.segredo.encode(), texto.encode(), hashlib.sha256).hexdigest()})
        req = urllib.request.Request(url, method=metodo, headers=cab, data=corpo.encode() if corpo is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                d = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            texto = e.read().decode("utf-8", "replace")[:300]
            try:
                d = json.loads(texto)
            except ValueError:
                msg = "a Bybit bloqueou o acesso deste país/rede" if e.code == 403 else texto or str(e)
                raise ErroBinance(e.code, msg)
        if d.get("retCode", 0) != 0:
            raise ErroBinance(d.get("retCode"), d.get("retMsg", "erro"))
        return d

    def sincronizar_relogio(self):
        d = self._req("GET", "/v5/market/time", publico=True)
        srv = int(d.get("time") or int(d["result"]["timeSecond"]) * 1000)
        self._delta = srv - int(time.time() * 1000)
        return self._delta

    # ---------------- público ----------------
    def regras(self):
        if self._regras is None:
            r, cursor = {}, ""
            while True:
                p = {"category": "linear", "limit": 1000}
                if cursor:
                    p["cursor"] = cursor
                res = self._req("GET", "/v5/market/instruments-info", p, publico=True)["result"]
                for s in res.get("list", []):
                    lot, pf = s.get("lotSizeFilter") or {}, s.get("priceFilter") or {}
                    r[s["symbol"]] = {"passo": float(lot.get("qtyStep") or 0.001), "min_qtd": float(lot.get("minOrderQty") or 0),
                                      "max_qtd": float(lot.get("maxMktOrderQty") or lot.get("maxOrderQty") or 1e12),
                                      "min_notional": float(lot.get("minNotionalValue") or 5), "tick": float(pf.get("tickSize") or 0.01)}
                cursor = res.get("nextPageCursor") or ""
                if not cursor or not res.get("list"):
                    break
            self._regras = r
        return self._regras

    def preco(self, par):
        return float(self._req("GET", "/v5/market/tickers", {"category": "linear", "symbol": par}, publico=True)["result"]["list"][0]["lastPrice"])

    # ---------------- conta (assinado) ----------------
    def _posicoes_brutas(self):
        lista, cursor = [], ""
        while True:
            p = {"category": "linear", "settleCoin": "USDT", "limit": 200}
            if cursor:
                p["cursor"] = cursor
            res = self._req("GET", "/v5/position/list", p, assinado=True)["result"]
            lista += res.get("list", [])
            cursor = res.get("nextPageCursor") or ""
            if not cursor or not res.get("list"):
                return lista

    def conta(self):
        """Patrimônio (com o lucro/prejuízo em aberto) e posições por moeda (+ comprado, − vendido)."""
        a = self._req("GET", "/v5/account/wallet-balance", {"accountType": "UNIFIED"}, assinado=True)["result"]["list"][0]
        f = lambda k: float(a.get(k) or 0)
        pos = {}
        for p in self._posicoes_brutas():
            q = float(p.get("size") or 0)
            if q and p.get("side") in ("Buy", "Sell"):
                pos[p["symbol"]] = pos.get(p["symbol"], 0.0) + (q if p["side"] == "Buy" else -q)
        return {"patrimonio": f("totalEquity"), "carteira": f("totalWalletBalance"), "disponivel": f("totalAvailableBalance"),
                "em_aberto": f("totalPerpUPL"), "posicoes": pos}

    def preparar_moeda(self, par, alavancagem):
        """Alavancagem máxima permitida na moeda (a exposição de verdade quem decide é a agência).
        Na conta unificada a margem já é cruzada."""
        x = str(int(alavancagem))
        try:
            self._req("POST", "/v5/position/set-leverage", {"category": "linear", "symbol": par, "buyLeverage": x, "sellLeverage": x}, assinado=True)
        except ErroBinance as e:
            if not _nao_mudou(e):
                raise

    def modo_unico(self):
        """Modo de posição única (one-way): uma posição líquida por moeda."""
        try:
            self._req("POST", "/v5/position/switch-mode", {"category": "linear", "coin": "USDT", "mode": 0}, assinado=True)
        except ErroBinance as e:
            if not _nao_mudou(e):
                raise

    def stops_abertos(self, par):
        """O stop de emergência (stop loss da posição) dessa moeda: [("sl", preço)] ou []."""
        for p in self._req("GET", "/v5/position/list", {"category": "linear", "symbol": par}, assinado=True)["result"].get("list", []):
            sl = float(p.get("stopLoss") or 0)
            if sl > 0 and float(p.get("size") or 0):
                return [("sl", sl)]
        return []

    def _stop(self, par, preco_txt):
        try:
            self._req("POST", "/v5/position/trading-stop", {"category": "linear", "symbol": par, "tpslMode": "Full", "positionIdx": 0,
                                                            "stopLoss": preco_txt, "slTriggerBy": "MarkPrice"}, assinado=True)
        except ErroBinance as e:
            if not _nao_mudou(e):
                raise

    def cancelar(self, par, ident):
        self._stop(par, "0")       # "0" = tira o stop loss da posição

    def stop_emergencia(self, par, lado_posicao, preco_stop):
        """Fica NA BYBIT (funciona com o PC desligado): fecha a posição inteira a mercado se o preço chegar lá."""
        self._stop(par, _fmt_preco(preco_stop, self.regras()[par].get("tick", 0.01)))
        return {"stop": preco_stop}

    def ordem_mercado(self, par, quantidade, reduzir=False, ident=None):
        """quantidade > 0 compra, < 0 vende."""
        b = {"category": "linear", "symbol": par, "side": "Buy" if quantidade > 0 else "Sell", "orderType": "Market",
             "qty": _fmt_qtd(abs(quantidade), self.regras()[par]["passo"]), "positionIdx": 0}
        if reduzir:
            b["reduceOnly"] = True
        if ident:
            b["orderLinkId"] = "".join(c for c in ident if c.isalnum() or c in "-_")[:36]
        r = self._req("POST", "/v5/order/create", b, assinado=True)["result"]
        return {"status": "enviada", "orderId": r.get("orderId"), "executedQty": b["qty"], "avgPrice": None}
