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
PADRAO = {"modo": "desligado", "corretora": "binance", "operar_neste_pc": False, "capital_papel_usd": 500, "alavancagem_binance": 10,
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
        self.estado.pop("tentativas", None)   # ao religar, a conta vazia testa as ordens de novo na hora (ex.: depois de editar a chave)
        self.estado.setdefault("erros", [])
        self.estado["modo"] = self.c["modo"]
        self.cli = cliente
        self.proxima = 0
        self.ativo = self.c["modo"] in ("papel", "testnet", "real") and self.c["operar_neste_pc"]
        ch = B.carregar_chave() or {}
        corretora = (self.c.get("corretora") or ch.get("corretora") or "binance").lower()
        self.nome = B.NOMES.get(corretora, corretora.title())
        self.estado["corretora"] = self.nome
        if self.c["modo"] in ("testnet", "real") and self.ativo and self.cli is None:
            if not ch or ch.get("modo") != self.c["modo"] or (ch.get("corretora") or "binance") != corretora:
                self.avisar(f"⚠️  Conta {self.nome}: falta a chave de {self.c['modo']} (rode o 9_conectar_binance.bat). Operação real DESLIGADA.")
                self.ativo = False
            else:
                self.cli = B.criar_cliente(corretora, self.c["modo"], ch["chave"], ch["segredo"], ch.get("frase"))
        if self.ativo and self.c["modo"] == "papel" and self.cli is None:
            self.cli = B.criar_cliente(corretora, "real") if corretora in ("bybit", "bitget") else B.Cliente("testnet")   # só regras e preços públicos
        if self.ativo:
            self.avisar(f"💵 Conta {self.nome} ligada em modo {self.c['modo'].upper()}"
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
        self.estado["n_ordens"] = self.estado.get("n_ordens", 0) + 1
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

    def _movimentos(self, conta, pat):
        """Depósito ou saque: o saldo da carteira mudou sem nenhuma ordem nossa e com as mesmas posições.
        Ajusta as referências das travas (senão um saque pareceria prejuízo e a trava do dia fecharia tudo)."""
        cart = conta.get("carteira", pat)
        pos = {k: round(v, 8) for k, v in (conta.get("posicoes") or {}).items()}
        ant, n = self.estado.get("ultimo_saldo"), self.estado.get("n_ordens", 0)
        if ant and ant.get("pos") == pos and ant.get("n") == n:
            d = cart - ant["carteira"]
            if abs(d) >= max(5.0, 0.02 * max(pat, 1.0)):
                for k in ("inicial", "inicio_dia"):
                    if self.estado.get(k):
                        self.estado[k] = max(0.0, self.estado[k] + d)
                if d < 0:   # sacou: a contagem do próximo lembrete recomeça daqui
                    self.estado["ref_saque"] = {"t": int(time.time() * 1000), "pat": pat}
                    self.estado.pop("lembrete_saque", None)
                else:
                    ref = self.estado.get("ref_saque")
                    if ref:
                        ref["pat"] += d
                self._anotar("movimentos", {"t": int(time.time() * 1000), "valor": round(d, 2)})
                self.avisar(f"💵 {'Saque' if d < 0 else 'Depósito'} de US$ {abs(d):,.2f} detectado na {self.nome} — travas ajustadas. "
                            "Se quiser a agência do mesmo tamanho, clique em ⚖️ Igualar ao saldo.")
        self.estado["ultimo_saldo"] = {"carteira": cart, "pos": pos, "n": n}

    def _foto_saldo(self, n_antes):
        """No fim do ciclo: se a agência mandou ordem agora, tira uma foto nova do saldo (taxas e lucro realizado já
        entram nela) — assim, no próximo ciclo, só depósito/saque mudam a carteira com as mesmas posições."""
        n = self.estado.get("n_ordens", 0)
        if n == n_antes or self.c["modo"] == "papel":
            return
        try:
            c = self._conta()
        except Exception:
            self.estado.pop("ultimo_saldo", None)
            return
        self.estado["ultimo_saldo"] = {"carteira": c.get("carteira", c["patrimonio"]),
                                       "pos": {k: round(v, 8) for k, v in (c.get("posicoes") or {}).items()}, "n": n}

    def _lembrete_saque(self, pat):
        """Regra de tirar lucro do bolso: quando a conta sobe X% (padrão 50%) ou passa 1 mês no lucro, sugere sacar uma parte."""
        agora = int(time.time() * 1000)
        ref = self.estado.setdefault("ref_saque", {"t": agora, "pat": pat})
        lucro, dias = pat - ref["pat"], (agora - ref["t"]) / 86_400_000
        alvo, mes, parte = self.c.get("saque_lucro_pct", 50), self.c.get("saque_a_cada_dias", 30), self.c.get("saque_parte_pct", 50)
        if lucro > 0 and (lucro >= ref["pat"] * alvo / 100 or dias >= mes):
            motivo = f"+{lucro / ref['pat'] * 100:.0f}% desde {time.strftime('%d/%m', time.localtime(ref['t'] / 1000))}" + (" · 1 mês" if dias >= mes else "")
            novo = not self.estado.get("lembrete_saque")
            self.estado["lembrete_saque"] = {"lucro": round(lucro, 2), "sugerido": round(lucro * parte / 100, 2), "motivo": motivo}
            if novo:
                self.avisar(f"💸 Hora de tirar lucro do bolso: a conta da {self.nome} ganhou US$ {lucro:,.2f} ({motivo}). "
                            f"Sugestão: sacar US$ {lucro * parte / 100:,.2f}. A agência percebe o saque sozinha.")
        else:
            self.estado.pop("lembrete_saque", None)

    def _testar_sem_saldo(self, ag):
        """Conta VAZIA: manda de verdade as ordens que mandaria (com o capital de teste) pra ver se a corretora as recebe.
        Sem saldo ela recusa (falta de margem) — a agência continua normal e mostra o aviso nos traders.
        Só tenta de novo quando o lado muda, a cada 30 min, ou ao religar a agência — pra não ficar insistindo."""
        cap = float(self.c.get("capital_papel_usd", 500))
        alvo, _ = self.alvo(ag, cap)
        regras = self.cli.regras()
        tent = self.estado.setdefault("tentativas", {})
        agora = int(time.time() * 1000)
        recusadas = {}
        for par, quer in sorted(alvo.items()):
            px = self._precos.get(par)
            if not px or par not in regras:
                continue
            q = B.arredondar(quer, regras[par]["passo"])
            if not q or abs(q) * px < regras[par]["min_notional"]:
                continue
            lado, moeda = (1 if q > 0 else -1), par.replace("USDT", "")
            ult = tent.get(par) or {}
            if ult.get("lado") == lado and agora - ult.get("t", 0) < self.c.get("teste_a_cada_minutos", 30) * 60_000:
                if ult.get("recusada"):
                    recusadas[par] = ult
                continue
            reg = {"t": agora, "lado": lado, "qtd": q, "usd": round(abs(q) * px, 2)}
            try:
                self.cli.ordem_mercado(par, q, ident=f"agencia-teste-{int(time.time())}-{moeda[:4]}")
            except B.ErroBinance as e:
                m = str(e.msg)
                falta = any(x in m.lower() for x in ("balance", "insufficient", "saldo", "available")) or str(e.codigo) in ("40762", "43012", "45110")
                permissao = "permission" in m.lower() or "permiss" in m.lower()
                reg["recusada"] = (("chave SEM permissão de ordens em Futuros — edite a chave na corretora (Futuros → Ordens: leitura e escrita)" if permissao
                                    else "falta de margem (conta sem saldo)" if falta else "recusada") + f" — resposta da {self.nome}: {m[:120]}")
                tent[par] = recusadas[par] = reg
                self.avisar(f"  🟡 [{self.c['modo']}] {'COMPRA' if lado > 0 else 'VENDA'} {abs(q):g} {moeda} (~US$ {reg['usd']:,.0f}) "
                            f"NÃO aberta na {self.nome}: {reg['recusada']}")
                ag.evento(agora, None, "🟡", f"{self.nome}: {'COMPRA' if lado > 0 else 'VENDA'} de {moeda} (~US$ {reg['usd']:,.0f}) "
                                             f"não abriu — {reg['recusada']}. Na agência a posição segue aberta.")
                continue
            # a corretora ACEITOU com a conta vazia (não devia): fecha tudo na hora, por segurança
            tent[par] = dict(reg, recusada=None)
            self._parar(f"teste sem saldo: a {self.nome} aceitou uma ordem de {moeda} — fechei tudo por segurança")
            return
        self.estado["recusadas"] = {p: {k: r[k] for k in ("t", "lado", "qtd", "usd", "recusada")} for p, r in recusadas.items()}
        for tr in ag.traders:
            r, p = recusadas.get(tr.par), tr.posicao
            tr.aviso_real = (f"Não aberta na {self.nome}: {r['recusada']}" if r and p and p.get("lado") == r["lado"] else None)

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
            self.avisar(f"⚠️  Não consegui fechar tudo na {self.nome} ({e}). FECHE MANUALMENTE no app da {self.nome}!")
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
            minimo = self.c.get("saldo_minimo_usd", 10)
            if pat < minimo and not conta["posicoes"]:
                # conectada, mas sem dinheiro ainda: não manda nada e não marca o ponto de partida (as travas usam ele)
                self.estado.update(patrimonio=round(pat, 2), em_aberto=0.0, posicoes={}, ultimo_ciclo=int(time.time() * 1000),
                                   status=f"sem saldo: conectada, esperando depósito (mínimo US$ {minimo})")
                for k in ("inicial", "inicio_dia", "dia"):
                    self.estado.pop(k, None)
                if not self.estado.get("avisou_sem_saldo"):
                    self.estado["avisou_sem_saldo"] = True
                    self.avisar(f"💵 Conta {self.nome} conectada e funcionando, mas sem saldo (US$ {pat:.2f}). "
                                "Quando você depositar, ela começa a copiar a agência sozinha.")
                if pat < 1 and self.c["modo"] in ("testnet", "real") and self.c.get("testar_sem_saldo", True):
                    self._testar_sem_saldo(ag)
                    n = len(self.estado.get("recusadas") or {})
                    if n:
                        motivos = {r.get("recusada", "").split(" — ")[0] for r in self.estado["recusadas"].values()}
                        self.estado["status"] = (f"sem saldo: {n} ordem(ns) tentada(s) e recusada(s) pela {self.nome} "
                                                 f"({' / '.join(sorted(motivos))}) — a agência segue normal")
                self._salvar()
                return
            self.estado.pop("avisou_sem_saldo", None)
            self.estado.pop("recusadas", None)
            for tr in ag.traders:
                if getattr(tr, "aviso_real", None):
                    tr.aviso_real = None
            hoje = time.strftime("%Y-%m-%d")
            if self.estado.get("dia") != hoje:
                self.estado.update(dia=hoje, inicio_dia=pat)
            if not self.estado.get("inicial") or self.estado["inicial"] < minimo:
                self.estado["inicial"] = pat
                self.estado["ref_saque"] = {"t": int(time.time() * 1000), "pat": pat}
                self.avisar(f"💵 Conta {self.nome}: começando com US$ {pat:,.2f} — copiando a agência a partir de agora.")
            self._movimentos(conta, pat)
            n_antes = self.estado.get("n_ordens", 0)
            self._lembrete_saque(pat)
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
            self._foto_saldo(n_antes)
            self._salvar()
        except B.ErroBinance as e:
            self._anotar("erros", {"t": int(time.time() * 1000), "erro": str(e)})
            self.estado["status"] = f"erro: {e}"
            self.avisar(f"⚠️  Conta {self.nome}: {e}")
            self._salvar()
        except Exception as e:
            self._anotar("erros", {"t": int(time.time() * 1000), "erro": repr(e)})
            self.estado["status"] = f"erro: {e}"
            self._salvar()
        finally:
            self.trava.release()
