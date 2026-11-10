"""Futuros perpétuos (simulados): LONG e SHORT com alavancagem, margem isolada, liquidação e funding.

Como o short funciona: a estratégia olha o preço "de cabeça pra baixo" (1/preço). Um sinal de compra
nesse espelho é um sinal de VENDA no preço real — o mesmo aluno, as mesmas regras, nos dois sentidos.

Custos (Binance USDT-M, aproximados): taxa taker 0,05% (ordens a mercado), maker 0,02% (ordens limitadas
da grade), funding a cada 8h (quem está comprado paga, vendido recebe, na média ~0,005%).
Liquidação: se a perda da posição comer a margem (menos a margem de manutenção), perde a margem inteira.
"""
import bisect

import indicadores
from estrategias import BARRAS_POR_DIA, checar_saida, fracao_entrada, niveis_de_entrada, pode_entrar

H8 = 8 * 3_600_000


def espelho(v):
    """Preço de cabeça pra baixo: comprar aqui = vender (short) no preço real."""
    return {"t": v["t"], "o": [1 / x for x in v["o"]], "h": [1 / x for x in v["l"]], "l": [1 / x for x in v["h"]],
            "c": [1 / x for x in v["c"]], "v": v["v"]}


def passo_ms(intervalo):
    return 86_400_000 // BARRAS_POR_DIA[intervalo]


def _fmt(x):
    return f"{x:,.2f}" if x >= 1 else f"{x:.5f}"


def confianca_da_escola(oos):
    """Quanto a escola confia no aluno: 0,5 (pouco) a 1,5 (muito), pelo Sharpe fora da amostra e a chance de não ser sorte."""
    if not oos:
        return 1.0
    c = max(0.5, min(1.5, 0.5 + (oos.get("sharpe") or 0) / 2))
    if (oos.get("dsr") or 0) < 0.5:
        c *= 0.8
    return round(max(0.5, c), 2)


def dimensionar(eq, caixa, preco, dist, cf, confianca=1.0, a_favor=True, fracao=1.0, regime=0):
    """O JULGAMENTO de cada operação (o mesmo na escola e ao vivo):
    1) Risco fixo: se o stop bater, perde no máximo `risco_por_operacao` do patrimônio (1%) — mais se a escola
       confia no aluno, metade se a operação vai CONTRA a tendência de 200 dias.
    2) Tamanho = risco ÷ distância do stop (stop longe → posição menor; stop perto → maior).
    3) Alavancagem = a maior que deixa a liquidação ALÉM do stop, limitada por um teto que depende da confiança
       e do regime (até `alavancagem_max`). Ela é consequência do risco, não uma aposta."""
    taxa = cf.get("taxa_taker", 0.0005) + cf.get("derrapagem", 0.0002)
    dist = max(dist, 0.002)
    contra = cf.get("fator_contra_tendencia", 0.5)
    risco = cf.get("risco_por_operacao", 0.01) * confianca * fracao * (1.0 if a_favor else contra)
    notional = eq * risco / (dist + 2 * taxa)
    lmax = cf.get("alavancagem_max", 10)
    lmin = min(lmax, cf.get("alavancagem_min", 1))
    # teto entre o mínimo e o máximo: sobe com a confiança, cai pela metade contra a tendência de 200 dias
    teto = round(lmin + (lmax - lmin) * min(1.0, confianca / 1.5) * (1.0 if a_favor else 0.5))
    seguro = int(1 / (dist + cf.get("margem_manutencao", 0.005) + cf.get("folga_liquidacao", 0.01)))
    L = max(lmin, min(teto, seguro), 1)
    limite = max(0.0, caixa) * cf.get("margem_maxima", 0.5)
    if notional / L > limite:
        notional = limite * L
    if L > seguro:
        porque = f"o mínimo da agência é {lmin}x — aqui a liquidação fica ANTES do stop e funciona como stop"
    elif seguro <= teto:
        porque = "a liquidação precisa ficar além do stop"
    else:
        porque = (f"o teto hoje é {teto}x (confiança {confianca:.2f}" + ("" if a_favor else ", operação contra a tendência de 200 dias") + ")")
    motivo = f"stop a {dist * 100:.1f}%, risco de US$ {eq * risco:.2f}; {L}x porque " + porque
    return {"notional": notional, "margem": notional / L, "alavancagem": L, "risco_usd": eq * risco,
            "a_favor": a_favor, "porque": motivo}


def nome_lado(lado):
    return "LONG ▲" if lado > 0 else "SHORT ▼"


def replay(est, d, v, p):
    """Em que posição a estratégia estaria AGORA se tivesse rodado o histórico todo (domínio de d/v)."""
    pos, n = None, len(v["c"])
    for i in range(1, n):
        if pos:
            if checar_saida(est, d, v, i, p, pos):
                pos = None
        elif pode_entrar(est, d, v, i, p):
            stop, alvo = niveis_de_entrada(d, i, p, v["c"][i])
            pos = {"preco": v["c"][i], "stop": stop, "alvo": alvo, "barras": 0, "maxc": v["c"][i]}
    preco = v["c"][-1]
    if pos and preco > pos["stop"] and (not pos["alvo"] or preco < pos["alvo"]):
        pos["maxc"] = max(pos["maxc"], preco)
        return pos
    return None


class Futuros:
    """Métodos de futuros do Trader (mixin)."""

    def _f(self, cfg):
        return cfg.get("futuros", {})

    # ------------------------------------------------------------------ básicos
    def _niveis_reais(self):
        p = self.posicao
        m = p.get("m")
        if not m:
            p["stop"] = p["alvo"] = None
            return
        if p["lado"] > 0:
            p["stop"], p["alvo"] = m.get("stop"), m.get("alvo")
        else:
            p["stop"] = 1 / m["stop"] if m.get("stop") else None
            p["alvo"] = 1 / m["alvo"] if m.get("alvo") else None

    def _liq(self, preco, lado, L, cfg):
        mmr = self._f(cfg).get("margem_manutencao", 0.005)
        return preco * (1 - 1 / L + mmr) if lado > 0 else preco * (1 + 1 / L - mmr)

    def _taxa_funding(self, cfg, ag):
        real = (getattr(ag, "funding_real", None) or {}).get(self.par)
        return real if real is not None else self._f(cfg).get("funding_8h", 0.00005)

    def _funding(self, t_fim, preco, cfg, ag=None):
        p = self.posicao
        if not p or "lado" not in p:
            return
        idx = t_fim // H8
        n = idx - p.get("funding_idx", idx)
        p["funding_idx"] = idx
        if n > 0:
            custo = p["lado"] * p["qtd"] * preco * self._taxa_funding(cfg, ag) * n
            self.caixa -= custo
            self.funding_pago = getattr(self, "funding_pago", 0.0) + custo
            p["funding"] = p.get("funding", 0.0) + custo

    # ------------------------------------------------------------------ o julgamento: tamanho e alavancagem
    def _julgar(self, lado, preco, stop, cfg, ag, t_fim, fracao=1.0):
        """Decide o tamanho e a alavancagem DESTA operação (ver dimensionar)."""
        regime = ag.regime(self.par, t_fim)
        cf = dict(self._f(cfg), fator_contra_tendencia=ag.fator_contra(self.time, self.estrategia))
        return dimensionar(self.patrimonio(), self.caixa, preco, abs(preco - stop) / preco, cf,
                           confianca=ag.confianca_viva(self.time, self.estrategia), a_favor=(regime == 0 or regime == lado),
                           fracao=fracao * self._fracao_humor(cfg), regime=regime)

    def _abrir_fut(self, lado, j, preco, t, m, cfg, ag, sincronizando=False, stop=None):
        """j = resultado de dimensionar(): notional, margem, alavancagem, risco e o porquê."""
        f = self._f(cfg)
        notional, margem, L = j["notional"], j["margem"], j["alavancagem"]
        if margem > self.caixa:
            notional, margem = self.caixa * L, self.caixa
        if notional < cfg["ordem_minima_usd"] or margem <= 0:
            return
        taxa = notional * f.get("taxa_taker", 0.0005)
        self.caixa -= taxa
        self.taxas_pagas = getattr(self, "taxas_pagas", 0.0) + taxa
        self.volume = getattr(self, "volume", 0.0) + notional
        self.posicao = {"lado": lado, "qtd": notional / preco, "preco": preco, "custo": margem, "margem": margem,
                        "notional": notional, "alavancagem": L, "preco_liquidacao": self._liq(preco, lado, L, cfg),
                        "t": t, "m": m, "humor": self.humor, "barras": 0, "maxc": preco, "taxa_abertura": taxa,
                        "funding": 0.0, "funding_idx": (t + passo_ms(self.intervalo)) // H8,
                        "risco_usd": j["risco_usd"], "porque": j["porque"], "stop_fixo": stop, "a_favor": j["a_favor"]}
        self._niveis_reais()
        if stop and not m:
            self.posicao["stop"] = stop
        self.trades_hoje += 1
        extra = " (entrou no movimento que já estava rolando)" if sincronizando else ""
        ag.evento(t, self, "📈" if lado > 0 else "📉",
                  f"{self.rotulo(ag)} abriu {nome_lado(lado)} {L}x: US$ {notional:,.0f} com US$ {margem:.2f} de margem — "
                  f"{j['porque']}{extra}")

    def _fechar_fut(self, preco, motivo, t, cfg, ag, liquidado=False, maker=False):
        p, self.posicao = self.posicao, None
        if liquidado:
            bruto, taxa = -p["margem"], 0.0
        else:
            bruto = p["lado"] * p["qtd"] * (preco - p["preco"])
            taxa = p["qtd"] * preco * self._f(cfg).get("taxa_maker" if maker else "taxa_taker", 0.0005)
        self.caixa += bruto - taxa
        self.taxas_pagas = getattr(self, "taxas_pagas", 0.0) + taxa
        self.volume = getattr(self, "volume", 0.0) + p["qtd"] * preco
        lucro = bruto - taxa - p.get("taxa_abertura", 0.0) - p.get("funding", 0.0)
        pct = lucro / p["margem"] * 100 if p["margem"] > 0 else 0.0
        if liquidado:
            self.liquidacoes = getattr(self, "liquidacoes", 0) + 1
            ag.evento(t, self, "💀", f"{self.rotulo(ag)} foi LIQUIDADO no {nome_lado(p['lado'])} {p['alavancagem']:g}x: "
                                     f"perdeu os US$ {p['margem']:.2f} de margem")
        self._registrar(p, preco, lucro, pct, motivo, t, cfg, ag, silencioso=liquidado,
                        sufixo=f" no {nome_lado(p['lado'])} {p['alavancagem']:g}x ({pct:+.1f}% da margem)")
        if self.trades and p.get("risco_usd"):
            self.trades[-1]["r"] = round(lucro / p["risco_usd"], 2)
        if self.trades and p.get("forcada") is not None:
            self.trades[-1]["forcada"] = p.get("forcada")
            self.trades[-1]["chance"] = p.get("chance")
        self._falar(t, ("Fechei " if lucro >= 0 else "Perdi ") + f"{'+' if lucro >= 0 else '-'}US$ {abs(lucro):.2f} "
                       f"({pct:+.1f}% na margem) no {nome_lado(p['lado'])} {p['alavancagem']:g}x — {motivo}.")
        ag.aprender(self, p, lucro, t)

    def _checar_liquidacao(self, o, h, l, t, cfg, ag):
        p = self.posicao
        liq, stop = p.get("preco_liquidacao"), p.get("stop")
        if not liq:
            return False
        if p["lado"] > 0:
            bateu = l <= liq and (o <= liq or stop is None or stop <= liq)
        else:
            bateu = h >= liq and (o >= liq or stop is None or stop >= liq)
        if bateu:
            self._fechar_fut(liq, "liquidação", t, cfg, ag, liquidado=True)
        return bateu

    def _checar_stop_fixo(self, o, h, l, t, cfg, ag):
        """Stop de proteção das estratégias de peso (que não têm stop próprio)."""
        p = self.posicao
        s = p.get("stop_fixo")
        if not s:
            return False
        if p["lado"] > 0 and l <= s:
            self._fechar_fut(min(s, o), "stop", t, cfg, ag)
            return True
        if p["lado"] < 0 and h >= s:
            self._fechar_fut(max(s, o), "stop", t, cfg, ag)
            return True
        return False

    # ------------------------------------------------------------------ alunos de sinal
    def _sinal_fut(self, est, v, d, ve, de, i, cfg, ag):
        o, h, l, c, t = v["o"][i], v["h"][i], v["l"][i], v["c"][i], v["t"][i]
        p = self.params
        if self.posicao and not self._checar_liquidacao(o, h, l, t, cfg, ag):
            lado = self.posicao["lado"]
            dd, vv = (d, v) if lado > 0 else (de, ve)
            r = checar_saida(est, dd, vv, i, p, self.posicao["m"])
            if r:
                self._fechar_fut(r[0] if lado > 0 else 1 / r[0], r[1], t, cfg, ag)
            else:
                self._niveis_reais()
                self._piramide(c, t, cfg, ag)
        self._checar_pausa(t, ag)
        if self.posicao or self.pausado_ate:
            return
        compra = pode_entrar(est, d, v, i, p)
        venda = ve is not None and pode_entrar(est, de, ve, i, p)
        if compra == venda:
            return
        lado = 1 if compra else -1
        dd, vv = (d, v) if compra else (de, ve)
        cc = vv["c"][i]
        stop, alvo = niveis_de_entrada(dd, i, p, cc)
        m = {"preco": cc, "stop": stop, "alvo": alvo, "barras": 0, "maxc": cc}
        stop_real = stop if lado > 0 else 1 / stop
        j = self._julgar(lado, c, stop_real, cfg, ag, t + passo_ms(self.intervalo), fracao_entrada(dd, i, p))
        self._abrir_fut(lado, j, c, t, m, cfg, ag)
        if self.posicao:
            self.posicao.update(unidades=1, ultimo=c, dist0=abs(c - stop_real) / c)

    def _piramide(self, c, t, cfg, ag):
        """PIRÂMIDE (regra das Tartarugas): a cada meia distância do stop a favor, soma mais uma unidade
        (metade do risco de uma entrada), até 4 unidades. Só aumenta o que já está ganhando."""
        pir = self._f(cfg).get("piramide") or {}
        p = self.posicao
        if not pir or not p or not p.get("dist0") or p.get("unidades", 1) >= pir.get("max_unidades", 1) or not p.get("stop"):
            return
        lado = p["lado"]
        if lado * (c / p["ultimo"] - 1) < p["dist0"] * pir.get("a_cada", 0.5):
            return
        j = self._julgar(lado, c, p["stop"], cfg, ag, t + passo_ms(self.intervalo), pir.get("fracao", 0.5))
        limite = self.caixa * self._f(cfg).get("margem_maxima", 0.8) - p["margem"]
        dn = min(j["notional"], max(0.0, limite) * j["alavancagem"])
        if dn < cfg["ordem_minima_usd"]:
            return
        taxa = dn * self._f(cfg).get("taxa_taker", 0.0005)
        self.caixa -= taxa
        self.taxas_pagas = getattr(self, "taxas_pagas", 0.0) + taxa
        self.volume = getattr(self, "volume", 0.0) + dn
        dq = dn / c
        p["preco"] = (p["qtd"] * p["preco"] + dq * c) / (p["qtd"] + dq)
        p["qtd"] += dq
        p["notional"] = p["qtd"] * p["preco"]
        p["margem"] = p["custo"] = p["margem"] + dn / j["alavancagem"]
        p["alavancagem"] = max(1, round(p["notional"] / p["margem"]))
        p["preco_liquidacao"] = self._liq(p["preco"], lado, p["notional"] / p["margem"], cfg)
        p["taxa_abertura"] = p.get("taxa_abertura", 0.0) + taxa
        p["risco_usd"] = p.get("risco_usd", 0.0) + j["risco_usd"]
        p["unidades"], p["ultimo"] = p.get("unidades", 1) + 1, c
        ag.evento(t, self, "➕", f"{self.rotulo(ag)} aumentou o {nome_lado(lado)} (pirâmide {p['unidades']}/{pir.get('max_unidades')}): "
                               f"+US$ {dn:,.0f}, a operação já estava ganhando")

    # ------------------------------------------------------------------ MODO 5 MIN: opera sempre
    def _falar(self, t, texto):
        self.fala, self.fala_t = texto, t

    def _processar_5m(self, est, v, d, ve, de, i, cfg, ag):
        """A cada vela de 5 min: se está fora, ABRE (pelo sinal da estratégia ou, sem sinal, no lado com maior
        chance de WIN segundo o modelo). Toda operação fecha no alvo, no stop ou no limite de 2 horas."""
        o, h, l, c, t = v["o"][i], v["h"][i], v["l"][i], v["c"][i], v["t"][i]
        md = cfg.get("modo", {})
        p = self.params
        t_fim = t + passo_ms(self.intervalo)
        limite = md.get("limite_horas", 2) * 3_600_000
        pos = self.posicao
        if pos and not self._checar_liquidacao(o, h, l, t, cfg, ag):
            lado = pos["lado"]
            r = None
            if pos.get("m"):
                dd, vv = (d, v) if lado > 0 else (de, ve)
                r = checar_saida(est, dd, vv, i, p, pos["m"])
                if r:
                    r = (r[0] if lado > 0 else 1 / r[0], r[1])
            else:
                st, al = pos.get("stop_fixo"), pos.get("alvo_fixo")
                if st and ((lado > 0 and l <= st) or (lado < 0 and h >= st)):
                    r = (min(st, o) if lado > 0 else max(st, o), "stop")
                elif al and ((lado > 0 and h >= al) or (lado < 0 and l <= al)):
                    r = (al, "alvo")
            if not r and t_fim - pos["t"] >= limite:
                r = (c, "limite de 2h")
            if r:
                self._fechar_fut(r[0], r[1], t, cfg, ag, maker=(r[1] == "alvo"))
            else:
                self._niveis_reais()
                if not pos.get("m"):
                    pos["stop"], pos["alvo"] = pos.get("stop_fixo"), pos.get("alvo_fixo")
        self._checar_pausa(t, ag)
        if self.posicao or self.pausado_ate:
            if self.posicao:
                self._fala_posicao(t_fim, md)
            return
        # 1) sinal da própria estratégia
        compra = pode_entrar(est, d, v, i, p) if est.id != "chance" else False
        venda = (ve is not None and pode_entrar(est, de, ve, i, p)) if est.id != "chance" else False
        cf = dict(self._f(cfg), risco_por_operacao=md.get("risco_por_operacao", 0.0025), piramide=None)
        cfg2 = dict(cfg, futuros=cf)
        if compra != venda:
            lado = 1 if compra else -1
            dd, vv = (d, v) if compra else (de, ve)
            cc = vv["c"][i]
            stop, alvo = niveis_de_entrada(dd, i, p, cc)
            m = {"preco": cc, "stop": stop, "alvo": alvo, "barras": 0, "maxc": cc}
            stop_real = stop if lado > 0 else 1 / stop
            j = self._julgar(lado, c, stop_real, cfg2, ag, t_fim, fracao_entrada(dd, i, p))
            self._abrir_fut(lado, j, c, t, m, cfg2, ag)
            if self.posicao:
                self.posicao.update(forcada=False, chance=None, limite_t=self.posicao["t"] + limite)
                self._falar(t, f"Minha estratégia ({est.nome}) deu sinal: abri {nome_lado(lado)} {j['alavancagem']}x.")
            return
        # 2) sem sinal: OBRIGADO a abrir no lado com maior chance de WIN
        x = ag.sinais_modelo(self.par, v, i, t_fim)
        a = d.get("atr", [None])[i] if d.get("atr") else None
        if x is None or not a:
            self._falar(t, "Esperando histórico suficiente pra calcular a chance de WIN.")
            return
        lado, chance, outra = ag.modelo().melhor_lado(x)
        stop = c - lado * md.get("stop_atr", 3.0) * a
        alvo = c + lado * md.get("alvo_atr", 3.0) * a
        j = self._julgar(lado, c, stop, cfg2, ag, t_fim, 1.0)
        self._abrir_fut(lado, j, c, t, None, cfg2, ag, stop=stop)
        if self.posicao:
            self.posicao.update(forcada=True, chance=round(chance, 3), chance_outro=round(outra, 3), alvo_fixo=alvo,
                                alvo=alvo, limite_t=self.posicao["t"] + limite)
            from modelo import NOME_SINAL
            motivos = [NOME_SINAL.get(n, n) for n in ag.modelo().explicar(x, lado)]
            self._falar(t, f"Sem sinal da estratégia: abri {nome_lado(lado)} {j['alavancagem']}x forçado — chance de WIN "
                           f"{chance * 100:.0f}% (contra {outra * 100:.0f}% do outro lado)"
                           + (f"; sinais a favor: {' e '.join(motivos)}" if motivos else "") + ".")

    def _fala_posicao(self, t_fim, md):
        p = self.posicao
        px = self.ultimo_preco or p["preco"]
        lucro = p["lado"] * p["qtd"] * (px - p["preco"])
        roe = lucro / p["margem"] * 100 if p.get("margem") else 0
        resta = max(0, (p.get("limite_t") or t_fim) - t_fim) // 60_000
        origem = f"forçado, chance {p['chance'] * 100:.0f}%" if p.get("forcada") else "sinal da estratégia"
        self._falar(t_fim, f"{nome_lado(p['lado'])} {p['alavancagem']:g}x ({origem}): {'+' if lucro >= 0 else '-'}US$ {abs(lucro):.2f} "
                           f"({roe:+.1f}% na margem). Fecho em até {resta} min.")

    # ------------------------------------------------------------------ alunos de peso (carteira contínua)
    def _stop_peso(self, d, i, c, lado):
        atr = (d.get("atr") or [None])[i] if d.get("atr") else None
        dist = (self.params.get("stop_atr", 3.0) * atr / c) if atr else 0.08
        return c * (1 - dist) if lado > 0 else c * (1 + dist)

    def _peso_fut(self, est, v, d, ve, de, i, cfg, ag):
        o, h, l, c, t = v["o"][i], v["h"][i], v["l"][i], v["c"][i], v["t"][i]
        if self.posicao and (self._checar_liquidacao(o, h, l, t, cfg, ag) or self._checar_stop_fixo(o, h, l, t, cfg, ag)):
            return
        self._checar_pausa(t, ag)
        p = self.params
        alvo = 0.0
        if not self.pausado_ate:
            alvo = est.peso(d, v, i, p) - (est.peso(de, ve, i, p) if ve is not None else 0.0)
        pos = self.posicao
        if pos and (abs(alvo) < 0.05 or (alvo > 0) != (pos["lado"] > 0)):
            self._fechar_fut(c, "sinal de saída", t, cfg, ag)
            pos = None
        if abs(alvo) < 0.1:
            return
        lado = 1 if alvo > 0 else -1
        stop = pos.get("stop_fixo") if pos else self._stop_peso(d, i, c, lado)
        j = self._julgar(lado, c, stop, cfg, ag, t + passo_ms(self.intervalo), abs(alvo))
        if not pos:
            self._abrir_fut(lado, j, c, t, None, cfg, ag, stop=stop)
        elif j["notional"] > 0 and abs(j["notional"] - pos["notional"]) / j["notional"] >= 0.25:
            self._ajustar_fut(j["notional"], c, t, cfg, ag)

    def _ajustar_fut(self, notional_novo, c, t, cfg, ag):
        p = self.posicao
        L, taxa_t = p["alavancagem"], self._f(cfg).get("taxa_taker", 0.0005)
        dq = (notional_novo - p["qtd"] * c) / c
        if dq > 0:
            dq = min(dq, max(0.0, self.caixa - p["margem"]) * L / c)
        else:
            dq = max(dq, -p["qtd"])
        if abs(dq) * c < cfg["ordem_minima_usd"]:
            return
        taxa = abs(dq) * c * taxa_t
        self.caixa -= taxa
        self.taxas_pagas = getattr(self, "taxas_pagas", 0.0) + taxa
        self.volume = getattr(self, "volume", 0.0) + abs(dq) * c
        if dq > 0:
            p["preco"] = (p["qtd"] * p["preco"] + dq * c) / (p["qtd"] + dq)
            p["taxa_abertura"] = p.get("taxa_abertura", 0.0) + taxa
        else:
            ganho = p["lado"] * (-dq) * (c - p["preco"])
            self.caixa += ganho
            self.lucro_realizado += ganho - taxa
        p["qtd"] += dq
        p["notional"] = p["qtd"] * p["preco"]
        p["margem"] = p["custo"] = p["notional"] / L
        p["preco_liquidacao"] = self._liq(p["preco"], p["lado"], L, cfg)
        ag.evento(t, self, "⚖️", f"{self.rotulo(ag)} ajustou o {nome_lado(p['lado'])} pra US$ {p['notional']:,.0f}")

    def sincronizar_fut(self, est, v, d, ve, de, t, cfg, ag):
        p, n, preco = self.params, len(v["c"]), v["c"][-1]
        t_fim = v["t"][-1] + passo_ms(self.intervalo)
        if est.tipo == "peso":
            alvo = est.peso(d, v, n - 1, p) - (est.peso(de, ve, n - 1, p) if ve is not None else 0.0)
            if abs(alvo) >= 0.1:
                lado = 1 if alvo > 0 else -1
                stop = self._stop_peso(d, n - 1, preco, lado)
                self._abrir_fut(lado, self._julgar(lado, preco, stop, cfg, ag, t_fim, abs(alvo)), preco, t, None, cfg, ag,
                                sincronizando=True, stop=stop)
            return
        for lado, dd, vv in ((1, d, v), (-1, de, ve)):
            if vv is None:
                continue
            m = replay(est, dd, vv, p)
            if m:
                stop_real = m["stop"] if lado > 0 else 1 / m["stop"]
                j = self._julgar(lado, preco, stop_real, cfg, ag, t_fim, fracao_entrada(dd, n - 1, p))
                self._abrir_fut(lado, j, preco, t, m, cfg, ag, sincronizando=True)
                if self.posicao:
                    self.posicao.update(unidades=1, ultimo=preco, dist0=abs(preco - stop_real) / preco)
                return

    def gatilho_fut(self, est, d, v, de, ve, i):
        """Texto do que falta pra abrir LONG ou SHORT, e a distância (+ subir / − cair)."""
        p = self.params
        if self.posicao:
            self.gatilho, self.distancia = None, None
            return
        try:
            txt = est.gatilho(d, v, i, p)
            dl = est.distancia(d, v, i, p)
            dm = est.distancia(de, ve, i, p) if ve is not None else None
            ds = None if dm is None else (1 / (1 + dm / 100) - 1) * 100
            partes = []
            if txt:
                partes.append(f"▲ LONG: {txt}" + (f" (falta {dl:+.2f}%)" if dl is not None else ""))
            if ve is not None:
                partes.append(f"▼ SHORT: o preço cair {abs(ds):.2f}% e dar o sinal ao contrário" if ds is not None
                              else "▼ SHORT: o mesmo sinal, ao contrário (preço caindo)")
            self.gatilho = " · ".join(partes) or None
            opcoes = [x for x in (dl, ds) if x is not None]
            self.distancia = round(min(opcoes, key=abs), 2) if opcoes else None
        except Exception:
            self.gatilho, self.distancia = None, None

    # ------------------------------------------------------------------ grade com filtro de tendência
    def _grade_fut(self, v, i, cfg, ag):
        o, h, l, c, t = v["o"][i], v["h"][i], v["l"][i], v["c"][i], v["t"][i]
        f, p = self._f(cfg), self.params
        maker, taker = f.get("taxa_maker", 0.0002), f.get("taxa_taker", 0.0005)
        esp = p["degrau"]
        n = max(2, int(round(p["faixa"] / esp)))
        L = self.alavancagem
        t_fim = t + passo_ms(self.intervalo)
        g = getattr(self, "grade_estado", None)
        if not g or not g.get("futuros"):
            g = self.grade_estado = {"futuros": True, "centro": c, "dir": 0, "lotes": {}, "cota": None, "funding_idx": t_fim // H8}
        lotes = g["lotes"]
        # funding a cada 8h sobre a posição líquida
        idx = t_fim // H8
        nf = idx - g.get("funding_idx", idx)
        g["funding_idx"] = idx
        if nf > 0 and lotes:
            custo = sum(x["lado"] * x["qtd"] for x in lotes.values()) * c * self._taxa_funding(cfg, ag) * nf
            self.caixa -= custo
            self.funding_pago = getattr(self, "funding_pago", 0.0) + custo
        # direção = tendência das velas de 4h (só velas já fechadas)
        direcao = ag.tendencia(self.par, p.get("filtro"), t_fim)
        if direcao != g["dir"]:
            if lotes:
                self._fechar_lotes(o, "a tendência virou", t, taker, ag)
            g["dir"], g["centro"], g["cota"] = direcao, o, None
            if direcao:
                ag.evento(t, self, "🧭", f"{self.rotulo(ag)} virou a grade pra {nome_lado(direcao)} (tendência de 4h)")
        if not g["cota"]:
            g["cota"] = max(cfg["ordem_minima_usd"], self.patrimonio() * f.get("margem_por_operacao", 0.25) * L / n)
        d_ = g["dir"]
        # 1) fecha os lotes que andaram 1 degrau a favor (ordem limitada → maker)
        for k in sorted(lotes, key=int):
            lt = lotes[k]
            alvo = lt["preco"] * (1 + lt["lado"] * esp)
            if lt["t"] < t and ((lt["lado"] > 0 and h >= alvo * 1.0002) or (lt["lado"] < 0 and l <= alvo * 0.9998)):
                self._fechar_lote(k, alvo, "degrau", t, maker, ag)
        # 2) abre lotes nos degraus que o preço tocou
        if d_ and self.patrimonio() > 0:
            for k in range(1, n + 1):
                nivel = g["centro"] * (1 - d_ * k * esp)
                if str(k) in lotes:
                    continue
                toca = (l <= nivel * 0.9998 and o > nivel * 0.98) if d_ > 0 else (h >= nivel * 1.0002 and o < nivel * 1.02)
                if toca:
                    qtd = g["cota"] / nivel
                    taxa = g["cota"] * maker
                    self.caixa -= taxa
                    self.taxas_pagas = getattr(self, "taxas_pagas", 0.0) + taxa
                    self.volume = getattr(self, "volume", 0.0) + g["cota"]
                    lotes[str(k)] = {"lado": d_, "qtd": qtd, "preco": nivel, "t": t, "taxa": taxa}
                    self.trades_hoje += 1
        # 3) sem lotes e o preço andou a favor: a grade acompanha
        if not lotes and d_ and ((d_ > 0 and c > g["centro"] * (1 + esp)) or (d_ < 0 and c < g["centro"] * (1 - esp))):
            g["centro"], g["cota"] = c, None
        # 4) saiu da faixa contra: stop em tudo e recomeça
        if lotes and ((d_ > 0 and c < g["centro"] * (1 - (n + 1) * esp)) or (d_ < 0 and c > g["centro"] * (1 + (n + 1) * esp))):
            self._fechar_lotes(c, "stop da faixa", t, taker, ag)
            g["centro"], g["cota"] = c, None
        # posição resumida pro painel/escritório
        if lotes:
            qtd = sum(x["qtd"] for x in lotes.values())
            preco = sum(x["qtd"] * x["preco"] for x in lotes.values()) / qtd
            lado = next(iter(lotes.values()))["lado"]
            self.posicao = {"lado": lado, "qtd": qtd, "preco": preco, "custo": qtd * preco / L, "margem": qtd * preco / L,
                            "notional": qtd * preco, "alavancagem": L, "preco_liquidacao": None, "t": min(x["t"] for x in lotes.values()),
                            "alvo": None, "stop": None, "humor": self.humor, "barras": 0, "maxc": c, "lotes": len(lotes)}
        else:
            self.posicao = None
        if not d_:
            self.gatilho = "esperando a tendência de 4h ficar clara pra montar a grade"
        else:
            prox = next((g["centro"] * (1 - d_ * k * esp) for k in range(1, n + 1)
                         if str(k) not in lotes and (g["centro"] * (1 - d_ * k * esp) - c) * d_ < 0), None)
            if prox:
                acao = "cair até" if d_ > 0 else "subir até"
                self.gatilho = f"{nome_lado(d_)}: {acao} {_fmt(prox)} (próximo degrau, {(prox / c - 1) * 100:+.2f}%)"
            else:
                self.gatilho = "o preço voltar pra faixa da grade"
            if lotes:
                self.gatilho += f"; {len(lotes)} lotes esperando andar {esp:.1%} a favor"
        self.distancia = None

    def _fechar_lote(self, k, preco, motivo, t, taxa_pct, ag):
        lt = self.grade_estado["lotes"].pop(k)
        bruto = lt["lado"] * lt["qtd"] * (preco - lt["preco"])
        taxa = lt["qtd"] * preco * taxa_pct
        self.caixa += bruto - taxa
        self.taxas_pagas = getattr(self, "taxas_pagas", 0.0) + taxa
        self.volume = getattr(self, "volume", 0.0) + lt["qtd"] * preco
        lucro = bruto - taxa - lt["taxa"]
        self.lucro_realizado += lucro
        margem = lt["qtd"] * lt["preco"] / self.alavancagem
        self.trades.append({"t_entrada": lt["t"], "t_saida": t, "entrada": lt["preco"], "saida": preco, "valor": margem,
                            "lucro": lucro, "pct": lucro / margem * 100 if margem else 0.0, "motivo": motivo,
                            "humor": self.humor, "lado": lt["lado"], "alavancagem": self.alavancagem})
        self.trades = self.trades[-60:]
        if lucro > 0:
            self.vitorias += 1
        else:
            self.derrotas += 1
        if motivo == "degrau":
            ag.evento(t, self, "✅" if lucro > 0 else "❌",
                      f"{self.rotulo(ag)} fechou um degrau ({nome_lado(lt['lado'])} {self.alavancagem:g}x): "
                      f"{'+' if lucro >= 0 else '-'}US$ {abs(lucro):.2f}")
        return lucro

    def _fechar_lotes(self, preco, motivo, t, taxa_pct, ag):
        lotes = self.grade_estado["lotes"]
        total = sum(self._fechar_lote(k, preco, motivo, t, taxa_pct, ag) for k in list(lotes))
        ag.evento(t, self, "🛑" if total < 0 else "✅", f"{self.rotulo(ag)} zerou a grade ({motivo}): "
                                                     f"{'+' if total >= 0 else '-'}US$ {abs(total):.2f}")

    def encerrar(self, preco, t, cfg, ag):
        """Fecha tudo a mercado (usado quando a mesa é desmontada)."""
        g = getattr(self, "grade_estado", None)
        if g and g.get("futuros") and g["lotes"]:
            self._fechar_lotes(preco, "mesa encerrada", t, self._f(cfg).get("taxa_taker", 0.0005), ag)
            self.posicao = None
        elif self.posicao and "lado" in self.posicao:
            self._fechar_fut(preco, "mesa encerrada", t, cfg, ag)
        elif self.posicao:
            self.caixa += self.posicao["qtd"] * preco * (1 - cfg["taxa"])
            self.posicao = None


def tendencia(buf, filtro, t_fim, cache):
    """+1 (média rápida acima da lenta), −1 (abaixo) ou 0 (sem dados), olhando só velas já fechadas em t_fim."""
    if not filtro:
        return 1
    if not buf:
        return 0
    passo = passo_ms(filtro["intervalo"])
    j = bisect.bisect_right(buf["t"], t_fim - passo) - 1
    if j < filtro["lenta"]:
        return 0
    chave = (filtro["intervalo"], filtro["rapida"], filtro["lenta"], buf["t"][j], buf["c"][j])
    if chave not in cache:
        if len(cache) > 500:
            cache.clear()
        c = buf["c"][:j + 1]
        r, le = indicadores.ema(c, filtro["rapida"])[-1], indicadores.ema(c, filtro["lenta"])[-1]
        cache[chave] = 0 if r is None or le is None else (1 if r > le else -1)
    return cache[chave]
