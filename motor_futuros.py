"""Futuros perpétuos (simulados): LONG e SHORT com alavancagem, margem isolada, liquidação e funding.

Como o short funciona: a estratégia olha o preço "de cabeça pra baixo" (1/preço). Um sinal de compra
nesse espelho é um sinal de VENDA no preço real — o mesmo aluno, as mesmas regras, nos dois sentidos.

Custos (Binance USDT-M, aproximados): taxa taker 0,05% (ordens a mercado), maker 0,02% (ordens limitadas
da grade), funding a cada 8h (quem está comprado paga, vendido recebe, na média ~0,005%).
Liquidação: se a perda da posição comer a margem (menos a margem de manutenção), perde a margem inteira.
"""
import bisect
import random

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


def _br(x, casas=2):
    """1234.5 → '1.234,50' (jeito brasileiro)."""
    return f"{x:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def usd_br(v):
    return f"{'+' if v >= 0 else '−'}US$ {_br(abs(v))}"


def lado_simples(lado):
    return "comprado" if lado > 0 else "vendido"


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


CARREIRA = {
    "estagiario": {"nome": "Estagiário", "max_alav": 5, "emoji": "🎒"},
    "trader": {"nome": "Trader", "max_alav": 7, "emoji": "💼"},
    "senior": {"nome": "Sênior", "max_alav": 10, "emoji": "🎖️"},
}
ORDEM_CARREIRA = ["estagiario", "trader", "senior"]


class Futuros:
    """Métodos de futuros do Trader (mixin)."""

    # ------------------------------------------------------------------ CARREIRA e LIMITE DIÁRIO
    def cargo(self):
        return getattr(self, "nivel", None) or "estagiario"

    def atualizar_carreira(self, t, ag):
        """Sobe de cargo provando resultado (e cai se piorar). Cargo = alavancagem máxima permitida."""
        hist = getattr(self, "hist_r", []) or []
        desde = getattr(self, "ops_desde_cargo", 0) + 1
        self.ops_desde_cargo = desde
        atual = ORDEM_CARREIRA.index(self.cargo())
        novo = atual
        media = lambda n: sum(hist[-n:]) / n if len(hist) >= n else None
        if atual == 0 and desde >= 50 and (media(50) or 0) > 0:
            novo = 1
        elif atual == 1 and desde >= 100 and (media(100) or 0) > 0.1:
            novo = 2
        elif atual > 0 and desde >= 30 and (media(50) if len(hist) >= 50 else 0) < -0.1:
            novo = atual - 1
        if novo != atual:
            self.nivel, self.ops_desde_cargo = ORDEM_CARREIRA[novo], 0
            c = CARREIRA[self.nivel]
            subiu = novo > atual
            ag.evento(t, self, "🎉" if subiu else "📉", f"{self.rotulo(ag)} {'foi PROMOVIDO' if subiu else 'foi REBAIXADO'} a {c['emoji']} {c['nome']}"
                                                   f" (resultado médio {(media(50) or 0):+.2f}R) — agora pode usar até {c['max_alav']}x")

    def bateu_limite_do_dia(self, t, cfg, ag):
        """Perdeu mais que X% do patrimônio desde o começo do dia (Brasília)? Então para por hoje."""
        lim = cfg.get("modo", {}).get("limite_perda_dia", 0.05)
        if not lim:
            return False
        from datetime import datetime, timedelta, timezone
        dia = datetime.fromtimestamp(t / 1000, timezone(timedelta(hours=-3))).strftime("%Y-%m-%d")
        if getattr(self, "dia_limite", None) != dia:
            self.dia_limite, self.eq_inicio_dia, self.parou_hoje = dia, self.patrimonio(), False
        if not getattr(self, "parou_hoje", False) and self.patrimonio() < self.eq_inicio_dia * (1 - lim):
            self.parou_hoje = True
            ag.evento(t, self, "🛑", f"{self.rotulo(ag)} perdeu mais de {lim:.0%} hoje e parou por hoje (volta amanhã)")
        return getattr(self, "parou_hoje", False)

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
    def _julgar(self, lado, preco, stop, cfg, ag, t_fim, fracao=1.0, ajuste=1.0):
        """Decide o tamanho e a alavancagem DESTA operação (ver dimensionar). `ajuste` = o que ele aprendeu
        sobre situações parecidas (≥1 = costuma dar certo → mais alavancagem; <1 = costuma dar errado → menos)."""
        regime = ag.regime(self.par, t_fim)
        cf = dict(self._f(cfg), fator_contra_tendencia=ag.fator_contra_trader(self))
        if ag.modo5m():   # carreira: a alavancagem máxima é CONQUISTADA
            esc = (cfg.get("modo", {}).get("carreira_alavancagem") or [CARREIRA[k]["max_alav"] for k in ORDEM_CARREIRA])
            cf["alavancagem_max"] = max(cf.get("alavancagem_min", 5), esc[ORDEM_CARREIRA.index(self.cargo())])
        conf = max(0.3, min(1.5, ag.confianca_trader(self) * ajuste))
        return dimensionar(self.patrimonio(), self.caixa, preco, abs(preco - stop) / preco, cf,
                           confianca=conf, a_favor=(regime == 0 or regime == lado),
                           fracao=fracao * self._fracao_humor(cfg), regime=regime)

    def _abrir_fut(self, lado, j, preco, t, m, cfg, ag, sincronizando=False, stop=None, maker=False):
        """j = resultado de dimensionar(): notional, margem, alavancagem, risco e o porquê."""
        f = self._f(cfg)
        notional, margem, L = j["notional"], j["margem"], j["alavancagem"]
        if margem > self.caixa:
            notional, margem = self.caixa * L, self.caixa
        if notional < cfg["ordem_minima_usd"] or margem <= 0:
            return
        taxa = notional * f.get("taxa_maker" if maker else "taxa_taker", 0.0005)
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
            f_ = self._f(cfg)
            taxa = p["qtd"] * preco * (f_.get("taxa_maker", 0.0002) if maker else f_.get("taxa_taker", 0.0005) + f_.get("derrapagem", 0.0)
                                       if self.intervalo == "5m" else f_.get("taxa_taker", 0.0005))
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
        if self.trades and p.get("x") and getattr(ag, "_guardar_x", False):
            ag._todas.append(dict(self.trades[-1], _x=p["x"], _lado=p["lado"], trader=self.nome, time=self.time, par=self.par,
                                  alav=p["alavancagem"], margem=p["margem"], lucro_usd=lucro))
        self._falar(t, f"Fechei: {usd_br(lucro)} ({'+' if pct >= 0 else '−'}{_br(abs(pct), 1)}%) {'✅' if lucro >= 0 else '❌'}",
                    ("Fechei " if lucro >= 0 else "Perdi ") + f"{'+' if lucro >= 0 else '-'}US$ {abs(lucro):.2f} "
                    f"({pct:+.1f}% na margem) no {nome_lado(p['lado'])} {p['alavancagem']:g}x — {motivo}.")
        ag.aprender(self, p, lucro, t)
        if hasattr(ag, "registrar_esfriamento"):
            ag.registrar_esfriamento(p, lucro, t)
        if hasattr(ag, "registrar_conta_real"):
            ag.registrar_conta_real(self, p, lucro, t)
        self._aprender_com_operacao(p, lucro, t, ag)

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

    # ------------------------------------------------------------------ cada funcionário é INDEPENDENTE
    def meu_estilo(self):
        """Personalidade própria (sorteada uma vez): até onde busca o alvo, onde põe o stop, quanta chance
        exige pra apostar cheio e quanto ousa. Dois robôs da mesma moeda decidem diferente."""
        if not getattr(self, "estilo", None) or "paciencia_min" not in self.estilo:
            rnd = random.Random(f"estilo|{self.time}|{self.nome}|{self.criado_em}")
            e = {"alvo_atr": rnd.choice([4, 5, 6, 7, 8]), "stop_atr": rnd.choice([3, 3.5, 4, 5]),
                 "corte": round(rnd.uniform(0.47, 0.55), 3), "ousadia": round(rnd.uniform(0.7, 1.3), 2),
                 "paciencia_min": rnd.choice([10, 20, 30, 45]), "virada": round(rnd.uniform(0.05, 0.12), 3),
                 "trail_atr": rnd.choice([1.5, 2.0, 2.5])}
            jeito = []
            jeito.append("ousado" if e["ousadia"] >= 1.15 else "cauteloso" if e["ousadia"] <= 0.85 else "equilibrado")
            jeito.append("paciente" if e["alvo_atr"] >= 7 else "rápido" if e["alvo_atr"] <= 4 else "")
            jeito.append("exigente" if e["corte"] >= 0.53 else "")
            jeito.append("teimoso" if e["paciencia_min"] >= 45 else "")
            e["jeito"] = ", ".join(x for x in jeito if x)
            self.estilo = e
        return self.estilo

    def meu_modelo(self, ag):
        """Modelo de chance PRÓPRIO: nasce de uma cópia do modelo da agência, com o 'jeito' dele (pesos levemente
        diferentes), e daí em diante aprende SÓ com as operações dele."""
        if getattr(self, "_mod", None) is None:
            from modelo import ModeloChance
            if not getattr(self, "modelo_pesos", None):
                base = ag.modelo().para_dict()
                rnd = random.Random(f"modelo|{self.time}|{self.nome}|{self.criado_em}")
                mexe = lambda w: [x * (1 + rnd.uniform(-0.4, 0.4)) + rnd.gauss(0, 0.03) for x in w]
                self.modelo_pesos = {"long": mexe(base["long"]), "short": mexe(base["short"]), "vistos": 0, "acertos": 0}
            self._mod = ModeloChance(self.modelo_pesos)
        return self._mod

    # ================================================================== ESTRATÉGIA DE APRENDIZADO
    # 1) cada VELA: o modelo dele aprende o que teria acontecido, com o jeito dele (Agencia.processar_vela)
    # 2) cada OPERAÇÃO: o modelo aprende mais forte com o que ele mesmo fez + anota a SITUAÇÃO (lado, tendência,
    #    volatilidade) e vira uma regra: situação que costuma dar errado → menos alavancagem e evita o lado
    # 3) a cada 30 OPERAÇÕES: um EXPERIMENTO no próprio jeito (alvo, stop, paciência...): fica se melhorar
    # 4) a EMPRESA: contratado nasce copiando o melhor do time; toda semana o pior recebe mentoria do melhor
    @staticmethod
    def situacao(x, lado):
        t4 = "alta" if x[8] > 0 else "queda" if x[8] < 0 else "sem tendência"
        vol = "volátil" if x[7] > 0.2 else "calmo"
        return f"{'LONG' if lado > 0 else 'SHORT'} · 4h em {t4} · mercado {vol}"

    def ajuste_situacao(self, x, lado):
        """(multiplicador, média encolhida em R, nº de casos) do que ele já viveu nessa situação."""
        rs = (getattr(self, "situacoes", None) or {}).get(self.situacao(x, lado)) or []
        if not rs:
            return 1.0, 0.0, 0
        n = len(rs)
        media = sum(rs) / n * n / (n + 15)          # encolhe: poucos casos quase não mudam nada
        return max(0.4, min(1.4, 1 + media)), media, n

    def peso_mesa(self, ag):
        """Quanto ele confia na mesa compartilhada × no próprio modelo pra escolher o LADO, pelo que cada um
        acertou nas decisões dele (só os casos em que um lado ganharia e o outro não)."""
        cl = ag._cfg_lado()
        w0 = cl.get("peso_inicial", 0.7)
        c = getattr(self, "calib_lado", None) or {}
        m, p = c.get("mesa", []), c.get("proprio", [])
        if len(m) < cl.get("min_casos", 20):
            return w0
        dif = sum(m) / len(m) - sum(p) / len(p)
        return round(max(0.2, min(0.95, w0 + 3 * dif)), 2)

    def _aprender_com_operacao(self, p, lucro, t=None, ag=None):
        x = p.get("x")
        if not x or getattr(self, "_mod", None) is None and not getattr(self, "modelo_pesos", None):
            return
        from modelo import ModeloChance
        if getattr(self, "_mod", None) is None:
            self._mod = ModeloChance(self.modelo_pesos)
        y = 1 if lucro > 0 else 0
        if not (ag is not None and ag._cfg_lado().get("ativo")):
            # (com a mesa de lado ligada, o modelo aprende o LADO pelo resultado neutro de 2h — ver Agencia._resolver_lados;
            #  aprender aqui com "eu ganhei?" ensinaria errado: depende das saídas dele, não só do lado)
            (self._mod.long if p["lado"] > 0 else self._mod.short).aprender(x, y, 0.03)
        self._mod.vistos += 1
        self._mod.acertos += y
        # regra por situação
        r = max(-3.0, min(4.0, lucro / p["risco_usd"])) if p.get("risco_usd") else (1.0 if lucro > 0 else -1.0)
        sit = getattr(self, "situacoes", None) or {}
        chave = self.situacao(x, p["lado"])
        sit[chave] = (sit.get(chave, []) + [round(r, 3)])[-40:]
        self.situacoes = sit
        if ag is not None and t is not None:
            n = len(sit[chave])
            if n in (15, 30):
                m = sum(sit[chave]) / n
                if abs(m) >= 0.15:
                    ag.evento(t, self, "📚", f"{self.rotulo(ag)} aprendeu: '{chave}' {'costuma dar CERTO' if m > 0 else 'costuma dar ERRADO'} "
                                            f"pra ele ({m:+.2f}R em {n} operações) — {'vai com mais confiança' if m > 0 else 'vai evitar e usar menos alavancagem'}")
            self._experimentar(r, t, ag)
            self.atualizar_carreira(t, ag)

    PARAMS_EXPERIMENTO = {"alvo_atr": [3, 4, 5, 6, 7, 8, 10], "stop_atr": [2.5, 3, 3.5, 4, 5, 6],
                          "paciencia_min": [10, 20, 30, 45, 60], "virada": [0.04, 0.06, 0.08, 0.1, 0.12, 0.15]}

    def _experimentar(self, r, t, ag):
        """Testa UMA mudança no próprio jeito por 30 operações e compara com as 30 anteriores."""
        e = self.meu_estilo()
        hist = getattr(self, "hist_r", [])
        hist = (hist + [r])[-200:]
        self.hist_r = hist
        self.ops_aprendidas = getattr(self, "ops_aprendidas", 0) + 1
        exp = getattr(self, "experimento", None)
        if exp:
            exp["n"] += 1
            exp["soma"] += r
            if exp["n"] >= 30:
                novo, base = exp["soma"] / exp["n"], exp["base"]
                ficou = novo > base + 0.05
                if not ficou:
                    e[exp["param"]] = exp["antes"]
                self.experimentos = (getattr(self, "experimentos", []) + [{"t": t, "param": exp["param"], "antes": exp["antes"],
                                     "depois": exp["depois"], "base": round(base, 3), "novo": round(novo, 3), "ficou": ficou}])[-20:]
                ag.evento(t, self, "🧪", f"{self.rotulo(ag)} terminou um experimento: {exp['param']} {exp['antes']} → {exp['depois']} "
                                        f"deu {novo:+.2f}R por operação (antes {base:+.2f}R) — " + ("FICA com a mudança" if ficou else "volta como era"))
                self.experimento = None
            return
        if len(hist) >= 30 and self.ops_aprendidas % 30 == 0:
            rnd = random.Random(f"exp|{self.nome}|{self.time}|{len(hist)}|{t}")
            param = rnd.choice(list(self.PARAMS_EXPERIMENTO))
            valores = self.PARAMS_EXPERIMENTO[param]
            atual = e.get(param, valores[len(valores) // 2])
            k = min(range(len(valores)), key=lambda q: abs(valores[q] - atual))
            vizinhos = [valores[q] for q in (k - 1, k + 1) if 0 <= q < len(valores)]
            novo = rnd.choice(vizinhos)
            self.experimento = {"param": param, "antes": atual, "depois": novo, "base": sum(hist[-30:]) / 30, "n": 0, "soma": 0.0, "t": t}
            e[param] = novo

    # ------------------------------------------------------------------ MODO 5 MIN: opera sempre
    def _falar(self, t, curto, longo=None):
        """Fala CURTA (o balão, em linguagem simples) + a explicação completa (pra quem quiser ver os detalhes)."""
        self.fala, self.fala_t, self.explicacao = curto, t, longo or curto

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
            self._gerir_posicao(est, v, d, i, cfg, ag, t_fim, limite)
        self._checar_pausa(t, ag)
        if self.posicao or self.pausado_ate:
            if self.posicao:
                self._fala_posicao(t_fim, md)
            return
        if self.bateu_limite_do_dia(t, cfg, ag):
            self.ordem = None
            self._falar(t, "Parei por hoje 🛑", "Bati meu limite de perda do dia. Parei por hoje pra não piorar — amanhã volto com a cabeça fresca.")
            return
        if ag.esfriando(t_fim) and ag.batedor(t_fim) is not self:
            self.ordem = None
            b = ag.batedor(t_fim)
            self._falar(t, "Esfriando 🧊", f"A agência está numa fase ruim (US$ {ag.resultado_recente(t_fim):+.2f} nas últimas horas) e aprendeu que "
                        f"insistir nessas fases dá prejuízo. Fico de fora até passar; {b.nome if b else 'o batedor'} segue testando o mercado.")
            return
        cf = dict(self._f(cfg), risco_por_operacao=md.get("risco_por_operacao", 0.0025), piramide=None)
        cfg2 = dict(cfg, futuros=cf)
        # 0) ordem limitada da vela anterior: o preço passou por ela? (taxa maker, sem derrapagem)
        ordem = getattr(self, "ordem", None)
        if ordem:
            self.ordem = None
            lado, px = ordem["lado"], ordem["preco"]
            if (lado > 0 and l <= px) or (lado < 0 and h >= px):
                px = min(px, o) if lado > 0 else max(px, o)   # se abriu do lado bom, executa no preço melhor
                self._abrir_fut(lado, ordem["j"], px, t, ordem["m"], cfg2, ag, stop=ordem.get("stop_fixo"), maker=True)
                if self.posicao:
                    self.posicao.update(ordem["extra"], limite_t=self.posicao["t"] + limite)
                    ag.marcar_conta_real(self, self.posicao, t)
                    if not ordem["m"]:
                        self.posicao.update(stop=ordem["stop_fixo"], alvo=ordem["extra"].get("alvo_fixo"))
                    self._falar(t, f"Entrei {lado_simples(lado)} {ordem['j']['alavancagem']}x a {_br(px, 2 if px >= 1 else 5)}",
                                f"Minha ordem limitada executou: {nome_lado(lado)} {ordem['j']['alavancagem']}x a {_fmt(px)}"
                                f" (paguei taxa de ordem limitada, a mais barata). " + ordem["porque"])
                return
        # 1) decide o lado: sinal da estratégia ou, sem sinal, a maior chance de WIN (obrigatório)
        x = ag.sinais_modelo(self.par, v, i, t_fim)
        a = d.get("atr", [None])[i] if d.get("atr") else None
        if x is None or not a:
            self._falar(t, "Carregando dados…", "Esperando histórico suficiente pra calcular a chance de WIN.")
            return
        est_p = self.meu_estilo()
        sd = md.get("saidas") or {}
        if sd.get("alvo_atr") and not sd.get("usar_estilo", False):
            est_p = dict(est_p, alvo_atr=sd["alvo_atr"], stop_atr=sd.get("stop_atr", est_p["stop_atr"]))
        meu = self.meu_modelo(ag)
        pl, ps = meu.chances(x)
        lado_proprio = 1 if pl >= ps else -1
        lado_mesa, peso_mesa = lado_proprio, 0.0
        if ag._cfg_lado().get("ativo"):
            ml, ms_ = ag.mesa_lado().chances(x)
            lado_mesa = 1 if ml >= ms_ else -1
            peso_mesa = self.peso_mesa(ag)
            pl, ps = peso_mesa * ml + (1 - peso_mesa) * pl, peso_mesa * ms_ + (1 - peso_mesa) * ps
        # o que ele aprendeu sobre situações parecidas mexe na chance de cada lado
        aj_l, m_l, n_l = self.ajuste_situacao(x, 1)
        aj_s, m_s, n_s = self.ajuste_situacao(x, -1)
        pl, ps = max(0.0, min(1.0, pl + 0.1 * m_l)), max(0.0, min(1.0, ps + 0.1 * m_s))
        compra = pode_entrar(est, d, v, i, p) if est.id != "chance" else False
        venda = (ve is not None and pode_entrar(est, de, ve, i, p)) if est.id != "chance" else False
        # 1b) sem sinal aqui: alguma outra moeda do time (que nenhum colega usa) está bem melhor? Vai pedir pro gerente
        if compra == venda and md.get("trocar_moeda") and ag.modo5m():
            if self._talvez_trocar_moeda(ag, t, t_fim, max(pl, ps), md):
                return
        if compra != venda:
            lado = 1 if compra else -1
            dd, vv = (d, v) if compra else (de, ve)
            cc = vv["c"][i]
            st_m, _ = niveis_de_entrada(dd, i, p, cc)
            m = None   # a saída é a do próprio funcionário (stop, alvo, modelo, tempo), não o sinal de saída da estratégia
            stop = st_m if lado > 0 else 1 / st_m
            alvo = c + lado * est_p.get("alvo_atr", md.get("alvo_atr", 6.0)) * a
            forcada, fr_base = False, fracao_entrada(dd, i, p)
        else:
            lado = 1 if pl >= ps else -1
            fr_real = (getattr(ag, "funding_real", None) or {}).get(self.par)
            if fr_real is not None and abs(pl - ps) < 0.02 and abs(fr_real) > 0.00005:
                lado = -1 if fr_real > 0 else 1   # quase empate: fica do lado que RECEBE o funding
            m = None
            stop = c - lado * est_p.get("stop_atr", md.get("stop_atr", 4.0)) * a
            alvo = c + lado * est_p.get("alvo_atr", md.get("alvo_atr", 6.0)) * a
            forcada, fr_base = True, 1.0
        ent = ag._cfg_entrada()
        vant = None
        if not ent.get("obrigatoria", True):
            v_l, n_l2 = ag.vantagem_de(x, 1)
            v_s, n_s2 = ag.vantagem_de(x, -1)
            melhor, v_m, n_m = (1, v_l, n_l2) if v_l >= v_s else (-1, v_s, n_s2)
            if not forcada and lado != melhor:
                v_m, n_m = (v_l, n_l2) if lado > 0 else (v_s, n_s2)   # sinal da estratégia: vale a vantagem DO LADO dele
            if v_m < ent.get("min_vantagem_r", 0.05) or n_m < ent.get("min_casos", 40):
                self.ordem = None
                self._falar(t, "Esperando oportunidade 👀",
                            f"Olhei a situação agora ({ag.chave_situacao(x, melhor)}): a agência já viu {n_m} casos assim e eles deram "
                            f"{v_m:+.2f}R em média depois das taxas. Não compensa — espero a próxima vela.")
                return
            if forcada and lado != melhor:
                lado = melhor
                stop = c - lado * est_p.get("stop_atr", md.get("stop_atr", 4.0)) * a
                alvo = c + lado * est_p.get("alvo_atr", md.get("alvo_atr", 6.0)) * a
            vant = (v_m, n_m)
        chance, outra = (pl, ps) if lado > 0 else (ps, pl)
        if ag._cfg_lado().get("ativo"):
            ag.registrar_decisao_lado(self, self.par, v["t"][i], [round(z, 4) for z in x], lado, lado_mesa, lado_proprio)
        # 2) TAMANHO pela chance: obrigado a abrir sempre, mas pequeno quando a chance é fraca (menos taxa)
        tc = md.get("tamanho_pela_chance") or {}
        fr = 1.0
        if tc:
            corte = est_p.get("corte", tc.get("corte", 0.5))
            fr = max(tc.get("minimo", 0.05), min(1.0, (chance - corte) / max(1e-6, tc.get("cheio", 0.6) - tc.get("corte", 0.5))))
        ajuste, media_sit, n_sit = (aj_l, m_l, n_l) if lado > 0 else (aj_s, m_s, n_s)
        j = self._julgar(lado, c, stop, cfg2, ag, t_fim, fr_base * fr * est_p.get("ousadia", 1.0), ajuste)
        # margem = o caixa INICIAL dele, sempre (posição mínima). Conforme ele lucra, o caixa cresce mas a margem
        # continua a mesma: o risco em % do patrimônio vai diminuindo. Se ele estiver abaixo do inicial, usa o que tem.
        if md.get("margem_fixa_usd") or md.get("margem_caixa_inicial"):
            # margem fixa (ex.: US$ 200) ou o caixa INICIAL dele — nunca mais que 95% do caixa que ele tem agora
            base = md.get("margem_fixa_usd") or getattr(self, "capital_inicial", None) or getattr(self, "capital_recebido", 0) or self.caixa
            margem = min(base, self.caixa * 0.95)
            notional = margem * j["alavancagem"]
            j = dict(j, margem=margem, notional=notional, risco_usd=notional * abs(c - stop) / c)
        mult, minimo = md.get("multiplicador_margem", 1.0), md.get("margem_minima_usd", 0.0)
        if (mult != 1.0 or minimo) and not (md.get("margem_caixa_inicial") or md.get("margem_fixa_usd")):
            margem = min(max(j["margem"] * mult, minimo), self.caixa * 0.95)
            notional = margem * j["alavancagem"]
            # o risco de verdade agora é o tamanho novo × a distância até o stop (pra medir R corretamente)
            j = dict(j, margem=margem, notional=notional, risco_usd=notional * abs(c - stop) / c)
        extra = {"forcada": forcada, "chance": round(chance, 3), "chance_outro": round(outra, 3), "tamanho_pct": round(fr * 100), "atr0": a,
                 "x": [round(z, 4) for z in x], "ag_recente": round(ag.resultado_recente(t_fim), 2)}
        if alvo:
            extra.update(alvo_fixo=alvo, alvo=alvo)
        if forcada:
            from modelo import NOME_SINAL
            motivos = [NOME_SINAL.get(n, n) for n in meu.explicar(x, lado)]
            porque = (f"Sem sinal da estratégia, fui no lado que o MEU modelo acha melhor: {chance * 100:.0f}% contra {outra * 100:.0f}%"
                      + (f" (a favor: {' e '.join(motivos)})" if motivos else "") + ".")
        else:
            porque = f"Minha estratégia ({est.nome}) deu sinal; meu modelo dá {chance * 100:.0f}% de chance."
        porque += f" Meu jeito: {est_p['jeito']} (alvo {est_p['alvo_atr']:g} ATR, stop {est_p['stop_atr']:g} ATR)."
        if vant:
            porque += f" Vantagem comprovada: {vant[1]} casos parecidos deram {vant[0]:+.2f}R em média já com taxas."
        if peso_mesa:
            cal = getattr(self, "calib_lado", None) or {}
            pm = lambda l: f"{sum(l) / len(l) * 100:.0f}%" if l else "—"
            porque += (f" Lado calibrado: {peso_mesa * 100:.0f}% mesa (aprende com todos os traders, acerta {pm(cal.get('mesa', []))})"
                       f" + {100 - peso_mesa * 100:.0f}% meu modelo (acerta {pm(cal.get('proprio', []))}).")
        if n_sit >= 5:
            porque += (f" Já vivi {n_sit}× '{self.situacao(x, lado)}': {media_sit:+.2f}R em média"
                       + (", vou com mais confiança." if media_sit > 0.05 else ", vou com cuidado." if media_sit < -0.05 else "."))
        if getattr(self, "experimento", None):
            ex = self.experimento
            porque += f" (Testando {ex['param']} {ex['antes']}→{ex['depois']}: {ex['n']}/30.)"
        tamanho = "posição cheia" if fr >= 0.999 else f"posição de {fr * 100:.0f}% do tamanho (chance fraca = aposta pequena, menos taxa)"
        if md.get("entrada_limitada", True):
            self.ordem = {"lado": lado, "preco": c, "j": j, "m": m, "stop_fixo": stop if not m else None, "extra": extra,
                          "porque": porque + " " + tamanho.capitalize() + "."}
            self._falar(t, f"Ordem de {'compra' if lado > 0 else 'venda'} {j['alavancagem']}x em {_br(c, 2 if c >= 1 else 5)} ⏳",
                        f"Coloquei ordem limitada de {nome_lado(lado)} {j['alavancagem']}x a {_fmt(c)} — {tamanho}. {porque} "
                        "Se não executar, tento de novo em 5 min.")
            return
        self._abrir_fut(lado, j, c, t, m, cfg2, ag, stop=stop if not m else None)
        if self.posicao:
            self.posicao.update(extra, limite_t=self.posicao["t"] + limite)
            ag.marcar_conta_real(self, self.posicao, t)
            self._falar(t, f"Entrei {lado_simples(lado)} {j['alavancagem']}x", f"Abri {nome_lado(lado)} {j['alavancagem']}x — {tamanho}. {porque}")

    def _talvez_trocar_moeda(self, ag, t, t_fim, chance_atual, md):
        """Troca de moeda passando pelo gerente: na 1ª vela ele vai até o Claude pedir; na seguinte a troca vale.
        Cada moeda só pode ter UM trader por time; depois de trocar, espera um tempo antes de trocar de novo."""
        pedido = getattr(self, "troca", None)
        reservadas = {x.par for x in ag.do_time(self.time) if x is not self} | \
                     {(getattr(x, "troca", None) or {}).get("para") for x in ag.do_time(self.time) if x is not self}
        if pedido:
            self.troca = None
            if pedido["para"] in reservadas:
                self._falar(t, "O gerente negou: um colega já está nessa moeda.")
                return False
            antiga, self.par = self.par, pedido["para"]
            self.ultimo_preco = ag.ultimo_preco.get(self.par, self.ultimo_preco)
            self.ultima_troca_t = t
            self._falar(t, f"O gerente aprovou: agora opero {self.par[:-4]} ✅", f"Troquei de {antiga[:-4]} pra {self.par[:-4]} com o aval do gerente.")
            ag.evento(t, self, "🔄", f"{self.rotulo(ag)} foi no gerente e trocou de {antiga[:-4]} pra {self.par[:-4]}")
            return True
        if t - (getattr(self, "ultima_troca_t", 0) or 0) < md.get("troca_espera_min", 30) * 60_000:
            return False
        melhor, nota = None, chance_atual + 0.03
        meu = self.meu_modelo(ag)
        for par in ag.moedas_do_time(self.time):
            if par == self.par or par in reservadas:
                continue
            vv = ag._buf.get(f"{par}@5m")
            if not vv or not vv["t"] or vv["t"][-1] < t - 10 * 60_000:
                continue
            x = ag.sinais_modelo(par, vv, len(vv["t"]) - 1, t_fim)
            if x is None:
                continue
            pl, ps = meu.chances(x)
            sc = max(pl, ps)
            if sc > nota:
                melhor, nota = par, sc
        if not melhor:
            return False
        self.troca = {"para": melhor, "t": t, "chance": round(nota, 3)}
        self._falar(t, f"Vou no gerente pedir pra trocar pra {melhor[:-4]} 🚶",
                    f"Em {self.par[:-4]} não tem nada bom agora; em {melhor[:-4]} meu modelo vê {nota * 100:.0f}% de chance.")
        return True

    def _gerir_posicao(self, est, v, d, i, cfg, ag, t_fim, limite):
        """Saída INTELIGENTE (cada um com o seu jeito), revista a cada 5 min:
        1) stop e alvo; 2) andou 1 ATR a favor → stop no zero a zero; andou 2 ATR → stop acompanha o preço;
        3) depois da paciência mínima, reavalia com o próprio modelo: se a chance virou pro outro lado, sai;
        4) no fim das 2 horas, fecha."""
        o, h, l, c, t = v["o"][i], v["h"][i], v["l"][i], v["c"][i], v["t"][i]
        pos, e = self.posicao, self.meu_estilo()
        lado = pos["lado"]
        st, al = pos.get("stop_fixo"), pos.get("alvo_fixo")
        saida = pos.get("saida_pendente")
        if st is None and pos.get("stop"):
            st = pos["stop_fixo"] = pos["stop"]
        if st and ((lado > 0 and l <= st) or (lado < 0 and h >= st)):
            motivo = "stop no zero a zero" if lado * (st - pos["preco"]) >= 0 else ("stop móvel" if pos.get("stop_movido") else "stop")
            return self._fechar_fut(min(st, o) if lado > 0 else max(st, o), motivo, t, cfg, ag)
        if al and ((lado > 0 and h >= al) or (lado < 0 and l <= al)):
            return self._fechar_fut(al, "alvo", t, cfg, ag, maker=True)
        if saida:   # ordem limitada de saída da vela anterior: executou? senão sai a mercado
            px = saida["preco"]
            if (lado > 0 and h >= px) or (lado < 0 and l <= px):
                return self._fechar_fut(max(px, o) if lado > 0 else min(px, o), saida["motivo"] + " · ordem limitada", t, cfg, ag, maker=True)
            return self._fechar_fut(c, saida["motivo"] + " · a mercado", t, cfg, ag)
        a0 = pos.get("atr0") or (d.get("atr") or [None])[i] or c * 0.003
        ganho_atr = lado * (c - pos["preco"]) / a0
        # 2) protege o lucro
        sd = cfg.get("modo", {}).get("saidas") or {}
        za = sd.get("zero_a_zero_atr", 1.0)
        if za and ganho_atr >= za and lado * ((st or 0) - pos["preco"]) < 0:
            novo = pos["preco"] * (1 + lado * 0.001)          # zero a zero + as taxas
            pos["stop_fixo"] = pos["stop"] = novo
            pos["stop_movido"] = True
            self._falar(t, "Lucro protegido 🔒", f"Andou {ganho_atr:.1f} ATR a meu favor: movi o stop pro zero a zero. Agora não perco mais nessa.")
            return
        if ganho_atr >= sd.get("trail_inicio_atr", 2.0):
            novo = c - lado * (sd.get("trail_atr") or e.get("trail_atr", 2.0)) * a0
            if lado * (novo - (pos.get("stop_fixo") or novo)) > 0:
                pos["stop_fixo"] = pos["stop"] = novo
                pos["stop_movido"] = True
        # 3) reavalia com o próprio modelo (depois da paciência mínima)
        minutos = (t_fim - pos["t"]) / 60_000
        if sd.get("modelo_virou", True) and minutos >= e.get("paciencia_min", 20):
            x = ag.sinais_modelo(self.par, v, i, t_fim)
            if x is not None:
                pl, ps = self.meu_modelo(ag).chances(x)
                _, m_l, _ = self.ajuste_situacao(x, 1)          # mesma conta da entrada (com o que ele aprendeu)
                _, m_s, _ = self.ajuste_situacao(x, -1)
                pl, ps = max(0.0, min(1.0, pl + 0.1 * m_l)), max(0.0, min(1.0, ps + 0.1 * m_s))
                meu, outro = (pl, ps) if lado > 0 else (ps, pl)
                pos["chance_agora"] = round(meu, 3)
                # entrada pelo SINAL da estratégia: só sai por "modelo virou" se a virada for o dobro (evita girar à toa)
                exige = e.get("virada", 0.08) * (1 if pos.get("forcada", True) else 2)
                if outro - meu >= exige:
                    return self._sair_com_limitada(c, f"meu modelo virou ({nome_lado(-lado)} {outro * 100:.0f}% × {meu * 100:.0f}%)", t, cfg, ag)
        # 4) limite de tempo (a ordem de saída sai um pouco antes, pra dar tempo de executar como limitada)
        if t_fim - pos["t"] >= limite - 5 * 60_000:
            return self._sair_com_limitada(c, "limite de 2h", t, cfg, ag)

    def _sair_com_limitada(self, c, motivo, t, cfg, ag):
        """Saída sem pressa: põe ordem limitada no preço atual (taxa mais barata). Se não executar na próxima vela, sai a mercado."""
        if not cfg.get("modo", {}).get("saida_limitada", True):
            return self._fechar_fut(c, motivo, t, cfg, ag)
        self.posicao["saida_pendente"] = {"preco": c, "motivo": motivo}
        self._falar(t, "Saindo da posição…", f"Vou sair ({motivo}): coloquei ordem limitada a {_fmt(c)} pra pagar menos taxa.")

    def _fala_posicao(self, t_fim, md):
        p = self.posicao
        if p.get("saida_pendente"):
            return
        px = self.ultimo_preco or p["preco"]
        lucro = p["lado"] * p["qtd"] * (px - p["preco"])
        roe = lucro / p["margem"] * 100 if p.get("margem") else 0
        resta = max(0, (p.get("limite_t") or t_fim) - t_fim) // 60_000
        e = self.meu_estilo()
        origem = (f"forçado, chance {p['chance'] * 100:.0f}%" if p.get("forcada") else "sinal da estratégia") \
            + (f", {p['tamanho_pct']}% do tamanho" if p.get("tamanho_pct") and p["tamanho_pct"] < 100 else "")
        agora = f" Meu modelo ainda dá {p['chance_agora'] * 100:.0f}% pra esse lado, sigo." if p.get("chance_agora") else ""
        prot = " Stop já protegendo o lucro." if p.get("stop_movido") else ""
        self._falar(t_fim, f"{lado_simples(p['lado']).capitalize()} {p['alavancagem']:g}x · {usd_br(lucro)} ({'+' if roe >= 0 else '−'}{_br(abs(roe), 1)}%)"
                           + (" 🔒" if p.get("stop_movido") else ""),
                    f"{nome_lado(p['lado'])} {p['alavancagem']:g}x ({origem}): {'+' if lucro >= 0 else '-'}US$ {abs(lucro):.2f} "
                    f"({roe:+.1f}% na margem).{prot}{agora} Fecho no alvo, se o modelo virar ou em até {resta} min.")

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
