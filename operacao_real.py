"""OPERAÇÃO REAL: a conta de futuros da Binance copia a agência, na proporção.

Modos (config `conta_binance.modo`, e só no PC marcado com `conta_binance.operar_neste_pc = true` no SEU config.json):
  • "desligado" — nada acontece.
  • "papel"     — calcula as ordens que mandaria e só ANOTA (não precisa de chave). Bom pra conferir antes.
  • "testnet"   — manda ordens de verdade na Binance de TREINO (dinheiro de mentira).
  • "real"      — dinheiro de verdade.

Como funciona: a agência simulada decide; a conta da Binance segue. Pra cada moeda, o alvo é a soma das posições dos
traders × (patrimônio da conta ÷ patrimônio da agência). Se dois times estão em lados opostos na mesma moeda, a conta
fica só com a diferença (menos taxa). A cada minuto ela compara o alvo com o que tem e manda a ordem que falta —
só quando a diferença vale a pena (passa do mínimo da Binance e da tolerância), pra não ficar girando à toa.

TRAVAS: perda máxima no dia, piso (se o patrimônio cair abaixo, fecha tudo e PARA), teto de exposição, e o botão
"PARAR TUDO" (painel ou o arquivo dados/PARAR_REAL). Depois de parado, só volta quando você mandar.
"""
import json
import os
import threading
import time
from pathlib import Path

import binance_real as B

AQUI = Path(__file__).resolve().parent
ARQ = AQUI / "dados" / "operacao_real.json"
ARQ_PARAR = AQUI / "dados" / "PARAR_REAL"
PADRAO = {"modo": "desligado", "operar_neste_pc": False, "capital_papel_usd": 500, "alavancagem_binance": 10,
          "max_exposicao_x": 4.0, "perda_max_dia_pct": 15, "piso_pct": 50, "tolerancia_usd": 15, "tolerancia_pct": 5,
          "a_cada_segundos": 60, "stop_emergencia_pct": 20}


def _cfg(cfg):
    return dict(PADRAO, **((cfg or {}).get("conta_binance") or {}))


def carregar_estado():
    try:
        return json.loads(ARQ.read_text(encoding="utf-8"))
    except Exception:
        return {}


class Operacao:
    def __init__(self, cfg, avisar=print, cliente=None):
        self.c = _cfg(cfg)
        self.avisar = avisar
        self.trava = threading.Lock()
        self.estado = carregar_estado()
        self.estado.setdefault("ordens", [])
        self.estado.setdefault("erros", [])
        self.estado["modo"] = self.c["modo"]
        self.cli = cliente
        self.proxima = 0
        self.ativo = self.c["modo"] in ("papel", "testnet", "real") and self.c["operar_neste_pc"]
        if self.c["modo"] in ("testnet", "real") and self.ativo and self.cli is None:
            ch = B.carregar_chave()
            if not ch or ch.get("modo") != self.c["modo"]:
                self.avisar(f"⚠️  Conta Binance: falta a chave de {self.c['modo']} (rode o 9_conectar_binance.bat). Operação real DESLIGADA.")
                self.ativo = False
            else:
                self.cli = B.Cliente(self.c["modo"], ch["chave"], ch["segredo"])
        if self.ativo and self.c["modo"] == "papel" and self.cli is None:
            self.cli = B.Cliente("testnet")   # só pra regras e preços públicos
        if self.ativo:
            self.avisar(f"💵 Conta Binance ligada em modo {self.c['modo'].upper()}"
                        + (" (só anota as ordens, não manda nada)" if self.c["modo"] == "papel" else "")
                        + (" — DINHEIRO DE VERDADE" if self.c["modo"] == "real" else ""))

    # ------------------------------------------------------------------
    def _salvar(self):
        self.estado["salvo_em"] = int(time.time() * 1000)
        ARQ.parent.mkdir(exist_ok=True)
        tmp = ARQ.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.estado, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, ARQ)

    def _anotar(self, lista, item, n=60):
        self.estado[lista] = (self.estado.get(lista, []) + [item])[-n:]

    def parado(self):
        return bool(self.estado.get("parado")) or ARQ_PARAR.exists()

    def _conta(self):
        if self.c["modo"] == "papel":
            pos = self.estado.get("papel_posicoes") or {}
            caixa = self.estado.get("papel_caixa", float(self.c["capital_papel_usd"]))
            em_aberto = sum(q * (self._precos.get(p, 0) - self.estado.get("papel_preco", {}).get(p, 0)) for p, q in pos.items())
            return {"patrimonio": caixa + em_aberto, "carteira": caixa, "disponivel": caixa, "em_aberto": em_aberto, "posicoes": dict(pos)}
        return self.cli.conta()

    def _executar(self, par, qtd, preco, reduzir, motivo):
        ordem = {"t": int(time.time() * 1000), "par": par, "qtd": qtd, "preco_ref": preco, "motivo": motivo, "modo": self.c["modo"]}
        if self.c["modo"] == "papel":   # simula a execução (taxa a mercado)
            pos = self.estado.setdefault("papel_posicoes", {}); pm = self.estado.setdefault("papel_preco", {})
            caixa = self.estado.get("papel_caixa", float(self.c["capital_papel_usd"]))
            antes = pos.get(par, 0.0)
            if antes and (antes > 0) != (qtd > 0):      # reduz/inverte: realiza o lucro da parte fechada
                fecha = min(abs(qtd), abs(antes)) * (1 if antes > 0 else -1)
                caixa += fecha * (preco - pm.get(par, preco))
            novo = antes + qtd
            if novo and (not antes or (antes > 0) != (novo > 0) or abs(novo) > abs(antes)):
                pm[par] = preco if (not antes or (antes > 0) != (novo > 0)) else (antes * pm[par] + qtd * preco) / novo
            caixa -= abs(qtd) * preco * 0.00045
            pos[par] = novo if abs(novo) > 1e-12 else 0.0
            if not pos[par]:
                pos.pop(par); pm.pop(par, None)
            self.estado["papel_caixa"] = caixa
            ordem["status"] = "anotada (papel)"
        else:
            r = self.cli.ordem_mercado(par, qtd, reduzir=reduzir, ident=f"agencia-{int(time.time())}-{par[:3]}")
            ordem.update(status=r.get("status"), id=r.get("orderId"), executado=r.get("executedQty"), preco_medio=r.get("avgPrice"))
        self._anotar("ordens", ordem)
        lado = "COMPRA" if qtd > 0 else "VENDA"
        self.avisar(f"  💵 [{self.c['modo']}] {lado} {abs(qtd):g} {par.replace('USDT', '')} (~US$ {abs(qtd) * preco:,.0f}) — {motivo}")
        return ordem

    # ------------------------------------------------------------------
    def alvo(self, ag, patrimonio):
        vivos = [tr for tr in ag.traders if not getattr(tr, "demitido", False)]
        E = sum(tr.patrimonio() for tr in vivos)
        if E <= 0:
            return {}, 0.0
        k = patrimonio / E
        alvo = {}
        for tr in vivos:
            p = tr.posicao
            if p and p.get("lado") and p.get("qtd"):
                alvo[tr.par] = alvo.get(tr.par, 0.0) + p["lado"] * p["qtd"] * k
        bruto = sum(abs(q) * self._precos.get(par, 0) for par, q in alvo.items())
        teto = self.c["max_exposicao_x"] * patrimonio
        if bruto > teto > 0:   # trava de exposição
            alvo = {par: q * teto / bruto for par, q in alvo.items()}
        return alvo, k

    def _stops_emergencia(self):
        """Mantém, NA BINANCE, um stop de emergência por moeda (protege mesmo com o PC desligado).
        Fica a X% do preço atual, contra a posição, e é refeito quando o preço anda mais de 2% ou o lado muda."""
        dist = self.c["stop_emergencia_pct"] / 100
        conta = self.cli.conta()
        sos = self.estado.setdefault("sos", {})
        for par in set(conta["posicoes"]) | set(sos):
            q = conta["posicoes"].get(par, 0.0)
            abertos = self.cli.stops_abertos(par)
            if not q:
                for i, _ in abertos:
                    self.cli.cancelar(par, i)
                sos.pop(par, None)
                continue
            px = self._precos.get(par) or self.cli.preco(par)
            alvo = px * (1 - dist) if q > 0 else px * (1 + dist)
            ok = [p for _, p in abertos if abs(p / alvo - 1) < 0.02 and (p < px) == (q > 0)]
            if ok and len(abertos) == 1:
                continue
            for i, _ in abertos:
                self.cli.cancelar(par, i)
            self.cli.stop_emergencia(par, q, alvo)
            sos[par] = round(alvo, 6)

    def parar_tudo(self, motivo):
        """Fecha todas as posições e PARA (só volta quando você mandar)."""
        with self.trava:
            self._parar(motivo)

    def _parar(self, motivo):
        self.estado.update(parado=True, motivo=motivo, parado_em=int(time.time() * 1000), status="parado")
        if not hasattr(self, "_precos"):
            self._precos = {}
        try:
            conta = self._conta()
            for par, q in conta["posicoes"].items():
                regra = self.cli.regras().get(par, {"passo": 0.001})
                q2 = B.arredondar(-q, regra["passo"])
                if q2:
                    self._executar(par, q2, self._precos.get(par) or self.cli.preco(par), True, "PARAR TUDO: " + motivo)
            if self.c["modo"] in ("testnet", "real"):
                for par in list((self.estado.get("sos") or {})):
                    for i, _ in self.cli.stops_abertos(par):
                        self.cli.cancelar(par, i)
                self.estado["sos"] = {}
        except Exception as e:
            self._anotar("erros", {"t": int(time.time() * 1000), "erro": f"ao parar: {e}"})
            self.avisar(f"⚠️  Não consegui fechar tudo na Binance ({e}). FECHE MANUALMENTE no app da Binance!")
        self._salvar()
        self.avisar(f"⛔ OPERAÇÃO REAL PARADA: {motivo}. Pra voltar: botão 'Retomar' no painel (e apague dados/PARAR_REAL, se tiver criado).")

    def retomar(self):
        with self.trava:
            self.estado.update(parado=False, motivo=None)
            if ARQ_PARAR.exists():
                ARQ_PARAR.unlink()
            self.estado.pop("dia", None)   # recomeça a contagem do dia
            self._salvar()
        self.avisar("▶️  Operação real retomada.")

    def ciclo(self, ag, precos, forcar=False):
        """Chamado depois de cada processamento: confere travas e manda o que faltar."""
        if not self.ativo or (not forcar and time.time() < self.proxima):
            return
        self.proxima = time.time() + self.c["a_cada_segundos"]
        if not self.trava.acquire(blocking=False):
            return
        try:
            self._precos = {p: v for p, v in (precos or {}).items() if v}
            if self.parado():
                if ARQ_PARAR.exists() and not self.estado.get("parado"):
                    self._parar("arquivo PARAR_REAL")
                self.estado["status"] = "parado"
                return
            if not self.estado.get("preparado") and self.c["modo"] in ("testnet", "real"):
                self.cli.sincronizar_relogio()
                self.cli.modo_unico()
                for par in {tr.par for tr in ag.traders}:
                    self.cli.preparar_moeda(par, self.c["alavancagem_binance"])
                self.estado["preparado"] = True
            for par in {tr.par for tr in ag.traders}:
                if par not in self._precos:
                    self._precos[par] = self.cli.preco(par)
            conta = self._conta()
            pat = conta["patrimonio"]
            hoje = time.strftime("%Y-%m-%d")
            if self.estado.get("dia") != hoje:
                self.estado.update(dia=hoje, inicio_dia=pat)
            self.estado.setdefault("inicial", pat)
            self.estado.update(patrimonio=round(pat, 2), em_aberto=round(conta["em_aberto"], 2), posicoes=conta["posicoes"],
                               ultimo_ciclo=int(time.time() * 1000), status="ok")
            # TRAVAS
            if pat < self.estado["inicio_dia"] * (1 - self.c["perda_max_dia_pct"] / 100):
                return self._parar(f"perdeu mais de {self.c['perda_max_dia_pct']}% hoje (US$ {self.estado['inicio_dia']:.2f} → US$ {pat:.2f})")
            if pat < self.estado["inicial"] * self.c["piso_pct"] / 100:
                return self._parar(f"patrimônio abaixo do piso de {self.c['piso_pct']}% (US$ {pat:.2f} de US$ {self.estado['inicial']:.2f})")
            # ALVO × ATUAL
            alvo, k = self.alvo(ag, pat)
            self.estado["alvo"] = {p: round(q, 6) for p, q in alvo.items()}
            regras = self.cli.regras()
            for par in sorted(set(alvo) | set(conta["posicoes"])):
                atual, quer, px = conta["posicoes"].get(par, 0.0), alvo.get(par, 0.0), self._precos.get(par)
                if not px or par not in regras:
                    continue
                dif = quer - atual
                tol = max(regras[par]["min_notional"] * 1.05, self.c["tolerancia_usd"], abs(quer) * px * self.c["tolerancia_pct"] / 100)
                if abs(dif) * px < tol and not (quer == 0 and atual):
                    continue
                q = B.arredondar(dif, regras[par]["passo"])
                if not q:
                    continue
                if quer == 0 and atual:      # zerar: fecha exatamente o que tem
                    q = B.arredondar(-atual, regras[par]["passo"])
                reduzir = abs(quer) < abs(atual) and (quer == 0 or (quer > 0) == (atual > 0))
                if abs(q) * px < regras[par]["min_notional"] and not (reduzir and quer == 0):
                    continue
                motivo = ("zerar" if quer == 0 else "diminuir" if reduzir else "aumentar/abrir") + f" (alvo {quer:+.6g}, tinha {atual:+.6g})"
                self._executar(par, q, px, reduzir, motivo)
            if self.c["modo"] in ("testnet", "real") and self.c.get("stop_emergencia_pct"):
                self._stops_emergencia()
            self._salvar()
        except B.ErroBinance as e:
            self._anotar("erros", {"t": int(time.time() * 1000), "erro": str(e)})
            self.estado["status"] = f"erro: {e}"
            self.avisar(f"⚠️  Conta Binance: {e}")
            self._salvar()
        except Exception as e:
            self._anotar("erros", {"t": int(time.time() * 1000), "erro": repr(e)})
            self.estado["status"] = f"erro: {e}"
            self._salvar()
        finally:
            self.trava.release()
