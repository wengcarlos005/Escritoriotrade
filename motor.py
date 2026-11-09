"""O motor da agência: uma LIGA de 5 times de traders robôs.

• Cada time = 1 estratégia da Escola de Traders, com 5 traders (um por moeda).
• A cada R$ 500 de lucro, nasce um bebê trader no time (moeda nova, pago só com o lucro do time).
• Toda segunda-feira sai a rodada: o time com a melhor pontuação das últimas 4 semanas vira o TITULAR
  (o que operaria com dinheiro real no futuro); os outros ficam na RESERVA, em simulação.

Tudo aqui é SIMULADO: o dinheiro é de mentira, os preços são reais.
"""
import json
from datetime import datetime, timedelta, timezone

from estrategias import POR_ID, checar_saida, fracao_entrada, niveis_de_entrada, pode_entrar
from motor_futuros import Futuros, confianca_da_escola, espelho, passo_ms, tendencia

FUSO = timezone(timedelta(hours=-3))  # horário de Brasília
TAMANHO_BUFFER = 1400
SEMANA = 7 * 86_400_000

NOMES_TIME = {
    "seykota": "Time Seykota", "momentum": "Time Momentum", "donchian_conjunto": "Time Canais",
    "tartaruga": "Time Tartarugas", "weinstein": "Time Weinstein", "ptj200": "Time Tudor Jones",
    "williams": "Time Williams", "squeeze": "Time Explosão", "supertrend": "Time Supertrend",
    "connors": "Time Connors", "minervini": "Time Minervini", "raschke": "Time Raschke",
    "macd": "Time MACD", "bollinger": "Time Bollinger", "cruzamento": "Time Original",
}

EMOJI_HUMOR = {"perigo": "🚨", "alerta": "⚠️", "normal": "🙂", "confiante": "😎"}
FRASE_HUMOR = {
    "perigo": "entrou em PERIGO",
    "alerta": "ficou em alerta",
    "normal": "voltou ao normal",
    "confiante": "está confiante",
}


def quando(t):
    return datetime.fromtimestamp(t / 1000, FUSO)


def hhmm(t):
    return quando(t).strftime("%d/%m %H:%M")


def moeda(par):
    return par[:-4] if par.endswith("USDT") else par


def proxima_meia_noite(t):
    d = quando(t) + timedelta(days=1)
    return int(d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)


def proxima_segunda(t):
    """Próxima segunda-feira 00:00 (Brasília) depois de t."""
    d = quando(t)
    dias = (7 - d.weekday()) % 7 or 7
    alvo = (d + timedelta(days=dias)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(alvo.timestamp() * 1000)


class Trader(Futuros):
    def __init__(self, nome, emoji, par, capital_usd, tipo, t, time_id, estrategia, params):
        self.nome = nome
        self.emoji = emoji
        self.par = par
        self.tipo = tipo              # "trader" ou "bebe"
        self.time = time_id
        self.caixa = capital_usd
        self.posicao = None
        self.vitorias = 0
        self.derrotas = 0
        self.seq = 0
        self.vit_bonus = 0
        self.der_corte = 0
        self.humor = "normal"
        self.pausado_ate = 0
        self.trades_hoje = 0
        self.dia = quando(t).strftime("%Y-%m-%d")
        self.lucro_realizado = 0.0
        self.criado_em = t
        self.ultimo_preco = None
        self.trades = []
        self.taxas_pagas = 0.0
        self.volume = 0.0
        self.alavancagem = 1
        self.liquidacoes = 0
        self.funding_pago = 0.0
        est = POR_ID[estrategia]
        self.estrategia = estrategia
        self.estrategia_nome = est.nome
        self.estrategia_emoji = est.emoji
        self.params = dict(params)
        self.intervalo = params["intervalo"]

    @property
    def chave(self):
        return f"{self.par}@{self.intervalo}"

    @classmethod
    def de_dict(cls, d):
        o = cls.__new__(cls)
        o.__dict__.update(d)
        return o

    def para_dict(self):
        return dict(self.__dict__)

    def patrimonio(self):
        p = self.posicao
        if not p:
            return self.caixa
        px = self.ultimo_preco or p["preco"]
        if "lado" in p:  # futuros: caixa + lucro/prejuízo em aberto
            g = getattr(self, "grade_estado", None)
            if g and g.get("futuros"):
                return self.caixa + sum(x["lado"] * x["qtd"] * (px - x["preco"]) for x in g["lotes"].values())
            return self.caixa + p["lado"] * p["qtd"] * (px - p["preco"])
        return self.caixa + p["qtd"] * px

    def aplicar_params_novos(self):
        novos = getattr(self, "params_novos", None)
        if novos:
            self.params, self.intervalo, self.params_novos = novos, novos["intervalo"], None

    def rotulo(self, ag):
        return f"{self.nome} do {ag.time(self.time)['nome']}"

    # ------------------------------------------------------------------
    def processar(self, v, d, cfg, ag, ve=None, de=None):
        est = POR_ID[self.estrategia]
        p = self.params
        i = len(v["c"]) - 1
        t, c = v["t"][i], v["c"][i]
        self.ultimo_preco = c
        dia = quando(t).strftime("%Y-%m-%d")
        if dia != self.dia:
            self.dia, self.trades_hoje = dia, 0

        if not self.posicao and getattr(self, "params_novos", None):
            self.aplicar_params_novos()   # a próxima vela já vem no intervalo novo
            return
        if ag.futuros():
            if est.tipo == "grade":
                self._grade_fut(v, i, cfg, ag)
                return
            self._funding(t + passo_ms(self.intervalo), c, cfg, ag)
            if est.tipo == "peso":
                self._peso_fut(est, v, d, ve, de, i, cfg, ag)
            else:
                self._sinal_fut(est, v, d, ve, de, i, cfg, ag)
            self.gatilho_fut(est, d, v, de, ve, i)
            return
        if est.tipo == "grade":
            self._processar_grade(v, i, cfg, ag)
            return
        if est.tipo == "peso":
            self._processar_peso(est, v, d, i, cfg, ag)
        else:
            if self.posicao:
                r = checar_saida(est, d, v, i, p, self.posicao)
                if r:
                    self._fechar(r[0], r[1], t, cfg, ag)
            self._checar_pausa(t, ag)
            if not self.posicao and not self.pausado_ate and pode_entrar(est, d, v, i, p):
                fr = fracao_entrada(d, i, p) * self._fracao_humor(cfg)
                stop, alvo = niveis_de_entrada(d, i, p, c)
                self._abrir(self.caixa * fr, c, t, stop, alvo, cfg, ag)
        self.atualizar_gatilho(est, d, v, i)

    def _processar_grade(self, v, i, cfg, ag):
        o, h, l, c, t = v["o"][i], v["h"][i], v["l"][i], v["c"][i], v["t"][i]
        p, taxa = self.params, cfg["taxa"]
        esp, niveis = p["degrau"], max(2, int(round(p["faixa"] / p["degrau"])))
        g = getattr(self, "grade_estado", None)
        if not g:
            g = self.grade_estado = {"centro": c, "lotes": {}, "cota": self.patrimonio() / niveis}
        lotes = g["lotes"]
        # 1) vende os lotes que subiram um degrau (comprados em velas anteriores)
        for k in sorted(lotes, key=int):
            lt = lotes[k]
            alvo = lt["preco"] * (1 + esp)
            if lt["t"] < t and h >= alvo * 1.0002:
                receita = lt["qtd"] * alvo * (1 - taxa)
                lucro = receita - lt["custo"]
                self.caixa += receita
                self.taxas_pagas = getattr(self, "taxas_pagas", 0.0) + lt["qtd"] * alvo * taxa
                self.volume = getattr(self, "volume", 0.0) + lt["qtd"] * alvo
                self.lucro_realizado += lucro
                self.trades.append({"t_entrada": lt["t"], "t_saida": t, "entrada": lt["preco"], "saida": alvo, "valor": lt["custo"],
                                    "lucro": lucro, "pct": lucro / lt["custo"] * 100, "motivo": "degrau", "humor": self.humor})
                self.trades = self.trades[-60:]
                if lucro > 0:
                    self.vitorias += 1
                else:
                    self.derrotas += 1
                del lotes[k]
                ag.evento(t, self, "✅", f"{self.rotulo(ag)} vendeu um degrau: {'+' if lucro >= 0 else '-'}US$ {abs(lucro):.2f}")
        # 2) compra nos degraus que o preço tocou
        for k in range(1, niveis + 1):
            nivel = g["centro"] * (1 - k * esp)
            if str(k) not in lotes and l <= nivel * 0.9998 and o > nivel * 0.98:
                gasto = min(g["cota"], self.caixa)
                if gasto >= cfg["ordem_minima_usd"]:
                    lotes[str(k)] = {"qtd": gasto * (1 - taxa) / nivel, "preco": nivel, "custo": gasto, "t": t}
                    self.caixa -= gasto
                    self.taxas_pagas = getattr(self, "taxas_pagas", 0.0) + gasto * taxa
                    self.volume = getattr(self, "volume", 0.0) + gasto
        # 3) se o preço subiu e não há nada comprado, a grade sobe junto
        if not lotes and c > g["centro"] * (1 + esp):
            g["centro"] = c
        # posição "resumida" pro painel e o escritório
        if lotes:
            qtd = sum(x["qtd"] for x in lotes.values()); custo = sum(x["custo"] for x in lotes.values())
            self.posicao = {"qtd": qtd, "preco": custo * (1 - taxa) / qtd, "custo": custo, "t": min(x["t"] for x in lotes.values()),
                            "alvo": None, "stop": None, "humor": self.humor, "barras": 0, "maxc": c, "lotes": len(lotes)}
        else:
            self.posicao = None
        prox = next((g["centro"] * (1 - k * esp) for k in range(1, niveis + 1) if str(k) not in lotes and g["centro"] * (1 - k * esp) < c), None)
        fmt = (lambda x: f"{x:,.2f}" if x >= 1 else f"{x:.5f}")
        self.gatilho = (f"cair até {fmt(prox)} (próximo degrau de compra, {(prox / c - 1) * 100:+.2f}%)" if prox else "o preço voltar pra faixa da grade") + \
                       (f"; {len(lotes)} lotes esperando subir {esp:.1%} pra vender" if lotes else "")
        self.distancia = None

    def atualizar_gatilho(self, est, d, v, i):
        try:
            self.gatilho = None if self.posicao else est.gatilho(d, v, i, self.params)
            dist = None if self.posicao else est.distancia(d, v, i, self.params)
            self.distancia = None if dist is None else round(dist, 2)
        except Exception:
            self.gatilho, self.distancia = None, None

    def _processar_peso(self, est, v, d, i, cfg, ag):
        t, c = v["t"][i], v["c"][i]
        self._checar_pausa(t, ag)
        alvo = 0.0 if self.pausado_ate else est.peso(d, v, i, self.params) * self._fracao_humor(cfg)
        eq = self.patrimonio()
        atual = self.posicao["qtd"] * c / eq if self.posicao and eq > 0 else 0.0
        if alvo == 0 and self.posicao:
            self._fechar(c, "sinal de saída", t, cfg, ag)
        elif alvo > 0 and abs(alvo - atual) >= 0.1:
            if not self.posicao:
                self._abrir(alvo * eq, c, t, None, None, cfg, ag)
            else:
                delta = alvo * eq - self.posicao["qtd"] * c
                taxa = cfg["taxa"]
                if delta > 0:
                    delta = min(delta, self.caixa)
                    self.taxas_pagas = getattr(self, "taxas_pagas", 0.0) + delta * taxa
                    self.volume = getattr(self, "volume", 0.0) + delta
                    self.caixa -= delta
                    self.posicao["qtd"] += delta * (1 - taxa) / c
                    self.posicao["custo"] += delta
                else:
                    vende = min(self.posicao["qtd"], -delta / c)
                    receita = vende * c * (1 - taxa)
                    self.taxas_pagas = getattr(self, "taxas_pagas", 0.0) + vende * c * taxa
                    self.volume = getattr(self, "volume", 0.0) + vende * c
                    self.caixa += receita
                    self.posicao["qtd"] -= vende
                    self.posicao["custo"] -= receita
                ag.evento(t, self, "⚖️", f"{self.rotulo(ag)} ajustou a posição ({alvo:.0%})")

    def _fracao_humor(self, cfg):
        if not cfg["humor"].get("muda_tamanho_da_aposta", True):
            return 1.0
        return cfg["humor"]["fracao_do_caixa"][self.humor]

    def _checar_pausa(self, t, ag):
        if self.pausado_ate and t >= self.pausado_ate:
            self.pausado_ate = 0
            ag.evento(t, self, "🕹️", f"{self.rotulo(ag)} voltou do videogame")

    def _abrir(self, valor, preco, t, stop, alvo, cfg, ag, sincronizando=False):
        valor = min(valor, self.caixa)
        if valor < cfg["ordem_minima_usd"]:
            return
        self.caixa -= valor
        self.taxas_pagas = getattr(self, "taxas_pagas", 0.0) + valor * cfg["taxa"]
        self.volume = getattr(self, "volume", 0.0) + valor
        self.posicao = {"qtd": valor * (1 - cfg["taxa"]) / preco, "preco": preco, "custo": valor, "t": t,
                        "alvo": alvo, "stop": stop, "humor": self.humor, "barras": 0, "maxc": preco}
        self.trades_hoje += 1
        extra = " (entrou na tendência que já estava rolando)" if sincronizando else ""
        ag.evento(t, self, "📈", f"{self.rotulo(ag)} comprou US$ {valor:.2f}{extra}")

    def _fechar(self, preco, motivo, t, cfg, ag):
        p, self.posicao = self.posicao, None
        receita = p["qtd"] * preco * (1 - cfg["taxa"])
        self.taxas_pagas = getattr(self, "taxas_pagas", 0.0) + p["qtd"] * preco * cfg["taxa"]
        self.volume = getattr(self, "volume", 0.0) + p["qtd"] * preco
        lucro = receita - p["custo"]
        pct = lucro / p["custo"] * 100 if p["custo"] > 0 else 0.0
        self.caixa += receita
        self._registrar(p, preco, lucro, pct, motivo, t, cfg, ag, sufixo=f" ({pct:+.1f}%)")

    def _registrar(self, p, preco, lucro, pct, motivo, t, cfg, ag, sufixo="", silencioso=False):
        """Depois de fechar uma operação (à vista ou futuros): placar, humor e as regras do vídeo."""
        self.lucro_realizado += lucro
        tr = {"t_entrada": p["t"], "t_saida": t, "entrada": p["preco"], "saida": preco,
              "valor": p["custo"], "lucro": lucro, "pct": pct, "motivo": motivo, "humor": p["humor"]}
        if "lado" in p:
            tr.update(lado=p["lado"], alavancagem=p.get("alavancagem"))
        self.trades.append(tr)
        self.trades = self.trades[-60:]
        if lucro > 0:
            self.vitorias += 1
            self.vit_bonus += 1
            self.seq = self.seq + 1 if self.seq > 0 else 1
            if not silencioso:
                ag.evento(t, self, "✅", f"{self.rotulo(ag)} ganhou US$ {lucro:.2f}{sufixo}")
        else:
            self.derrotas += 1
            self.der_corte += 1
            self.seq = self.seq - 1 if self.seq < 0 else -1
            if not silencioso:
                ag.evento(t, self, "❌", f"{self.rotulo(ag)} perdeu US$ {abs(lucro):.2f}{sufixo}")

        antes = self.humor
        h = cfg["humor"]
        if self.seq <= -h["derrotas_para_perigo"]:
            self.humor = "perigo"
        elif self.seq < 0:
            self.humor = "alerta"
        elif self.seq >= h["vitorias_para_confiante"]:
            self.humor = "confiante"
        else:
            self.humor = "normal"
        if self.humor != antes:
            ag.evento(t, self, EMOJI_HUMOR[self.humor], f"{self.rotulo(ag)} {FRASE_HUMOR[self.humor]}")

        r = cfg["regras"]
        if not r.get("ativo", True):
            self.vit_bonus = self.der_corte = 0
        if self.vit_bonus >= r["vitorias_para_bonus"]:
            self.vit_bonus = 0
            ag.aporte(self, r["bonus_usd"])
            ag.evento(t, self, "🎁", f"{r['vitorias_para_bonus']} vitórias! O CEO deu +US$ {r['bonus_usd']} pro {self.rotulo(ag)}")
        if self.der_corte >= r["derrotas_para_corte"]:
            self.der_corte = 0
            corte = min(r["corte_usd"], max(0.0, self.caixa - r["capital_minimo_usd"]))
            if corte > 0:
                ag.aporte(self, -corte)
                ag.evento(t, self, "✂️", f"{r['derrotas_para_corte']} derrotas. O CEO tirou US$ {corte:.2f} do {self.rotulo(ag)}")

        c = cfg["cansaco"]
        if not c.get("ativo", True):
            return
        if self.seq == -c["derrotas_seguidas"]:
            self.pausado_ate = t + c["pausa_minutos"] * 60_000
            ag.evento(t, self, "🎮", f"{self.rotulo(ag)} perdeu {c['derrotas_seguidas']} seguidas e foi jogar videogame (volta {hhmm(self.pausado_ate)})")
        elif self.trades_hoje >= c["max_trades_dia"]:
            self.pausado_ate = proxima_meia_noite(t)
            ag.evento(t, self, "🎮", f"{self.rotulo(ag)} já fez {self.trades_hoje} operações hoje e foi pro videogame até amanhã")


class Agencia:
    def __init__(self, cfg, t, modo="simulacao"):
        self.cfg = cfg
        self.modo = modo
        self.criado_em = t
        self.cotacao_brl = cfg.get("cotacao_brl_padrao", 5.5)
        self.aportes_ceo = 0.0
        self.ultimo_t = {}
        self.ultimo_preco = {}
        self.eventos = []
        self.curva = []
        self.salvo_em = None
        self.times = []
        self.traders = []
        self.temporada = None
        self.sprint = None
        self.sprints = []
        self.mercado = "futuros" if cfg.get("futuros", {}).get("ativo") else "spot"
        self.versao = 4            # 3 = perfis de risco + pirâmide (2 = escola de futuros, risco fixo, julgamento, Comitê, aprendizado)
        self.aprendizado = {}
        self.caixa_empresa = 0.0
        self.funding_real = None
        self.fonte_dados = "spot"
        self._iniciar_temporarios()

    def _iniciar_temporarios(self):
        self._buf = {}
        self._tend = {}
        self.ao_evento = None

    def futuros(self):
        return getattr(self, "mercado", "spot") == "futuros"

    # --- aprendizado: cada operação fechada ensina alguma coisa ---------------------------------
    def _mem(self, chave):
        if not hasattr(self, "aprendizado") or self.aprendizado is None:
            self.aprendizado = {}
        return self.aprendizado.setdefault(chave, {"r": [], "r_contra": [], "anunciada": None})

    def aprender(self, tr, pos, lucro, t):
        """Guarda o resultado em R (lucro ÷ risco planejado). 1R = ganhou o que arriscou; −1R = bateu o stop."""
        risco = pos.get("risco_usd") or 0
        if risco <= 0:
            return
        r = max(-3.0, min(6.0, lucro / risco))
        m = self._mem(f"{tr.time}|{tr.estrategia}")
        m["r"] = (m["r"] + [round(r, 3)])[-60:]
        if not pos.get("a_favor", True):
            m["r_contra"] = (m["r_contra"] + [round(r, 3)])[-40:]
        c = self.confianca_viva(tr.time, tr.estrategia)
        ant = m.get("anunciada") or self.time(tr.time).get("confianca") or 1.0
        if abs(c - ant) >= 0.1:
            m["anunciada"] = c
            ult = m["r"][-20:]
            tm = self.time(tr.time)
            self.evento(t, None, "🧠", f"{tm['emoji']} {tm['nome']} aprendeu com as operações: confiança {ant:.2f} → {c:.2f} "
                                      f"(últimas {len(ult)}: {sum(ult) / len(ult):+.2f}R em média) — "
                                      + ("vai arriscar um pouco mais" if c > ant else "vai arriscar menos"))

    def confianca_viva(self, time_id, estrategia=None):
        """Confiança = o que a escola achou (prior) misturado com o que aconteceu ao vivo.
        Com poucas operações vale quase só a escola; com 20 operações, metade/metade (evita confundir sorte com habilidade)."""
        tm = self.time(time_id)
        prior = tm.get("confianca") or 1.0
        m = (getattr(self, "aprendizado", None) or {}).get(f"{time_id}|{estrategia or tm.get('estrategia')}")
        if not m or not m["r"]:
            return round(prior, 2)
        rs = m["r"][-40:]
        media = max(-0.9, min(1.0, sum(rs) / len(rs)))
        vivo = max(0.5, min(1.5, prior * (1 + media)))   # média 0R mantém o que a escola achou; +0,3R sobe 30%; −0,3R desce 30%
        w = len(rs) / (len(rs) + self.cfg.get("aprendizado", {}).get("operacoes_meio_peso", 20))
        return round((1 - w) * prior + w * vivo, 2)

    def fator_contra(self, time_id, estrategia=None):
        """Quanto arriscar CONTRA a tendência de 200 dias: começa em 50% e aprende com essas operações."""
        base = self.cfg.get("futuros", {}).get("fator_contra_tendencia", 0.5)
        tm = self.time(time_id)
        m = (getattr(self, "aprendizado", None) or {}).get(f"{time_id}|{estrategia or tm.get('estrategia')}")
        if not m or not m["r_contra"]:
            return base
        rs = m["r_contra"][-30:]
        aprendido = max(0.2, min(1.0, base + 0.5 * sum(rs) / len(rs)))
        w = len(rs) / (len(rs) + 10)
        return round((1 - w) * base + w * aprendido, 2)

    def reestudar(self, esc, t):
        """Boletim novo da escola (reestudo semanal com os dados mais recentes): cada time atualiza os parâmetros
        da sua estratégia e a confiança de partida. Quem está com posição aberta troca quando fechar."""
        por_id = {r["id"]: r for r in esc.get("resultados", [])}
        for tm in self.disputando():
            for est_id in (tm.get("membros") or [tm["estrategia"]]):
                r = por_id.get(est_id)
                if not r:
                    continue
                novos = r["params_atuais"]
                antigos = tm["params"] if not tm.get("membros") else None
                if not tm.get("membros"):
                    tm["params"], tm["intervalo"] = novos, novos["intervalo"]
                    if self.futuros():
                        tm["confianca"] = confianca_da_escola(r.get("oos"))
                mudou = False
                for tr in self.do_time(tm["id"]):
                    if tr.estrategia == est_id and tr.params != novos:
                        tr.params_novos = dict(novos)
                        mudou = True
                        if not tr.posicao:
                            tr.aplicar_params_novos()
                if mudou:
                    txt = ", ".join(f"{k} {antigos.get(k)}→{v}" for k, v in novos.items() if antigos and antigos.get(k) != v)
                    self.evento(t, None, "🎓", f"{tm['emoji']} {tm['nome']} reestudou com os dados mais novos"
                                              + (f": {txt}" if txt else "") + " (quem está posicionado troca ao fechar)")
        if self.futuros():
            com = esc.get("comite")
            for tm in self.disputando():
                if tm.get("membros") and com:
                    tm["confianca"] = confianca_da_escola(com.get("oos"))

    def resumo_aprendizado(self):
        saida = []
        for tm in self.times:
            if tm.get("especial"):
                continue
            for est in (tm.get("membros") or [tm.get("estrategia")]):
                m = (getattr(self, "aprendizado", None) or {}).get(f"{tm['id']}|{est}") or {"r": [], "r_contra": []}
                rs = m["r"]
                saida.append({"time": tm["id"], "estrategia": est, "nome": POR_ID[est].nome if est in POR_ID else est,
                              "operacoes": len(rs), "media_r": round(sum(rs) / len(rs), 2) if rs else None,
                              "acerto_pct": round(sum(1 for x in rs if x > 0) / len(rs) * 100) if rs else None,
                              "confianca_escola": tm.get("confianca") or 1.0, "confianca_agora": self.confianca_viva(tm["id"], est),
                              "contra_operacoes": len(m["r_contra"]), "fator_contra": self.fator_contra(tm["id"], est),
                              "ultimos_r": rs[-20:]})
        return saida

    def regime(self, par, t_fim):
        """Tendência de longo prazo (velas diárias, média 50 × 200): +1 alta, −1 baixa, 0 sem dados."""
        filtro = self.cfg.get("futuros", {}).get("regime", {"intervalo": "1d", "rapida": 50, "lenta": 200})
        return tendencia(self._buf.get(f"{par}@{filtro['intervalo']}"), filtro, t_fim, self._tend)

    def tendencia(self, par, filtro, t_fim):
        if not filtro:
            return 1
        return tendencia(self._buf.get(f"{par}@{filtro['intervalo']}"), filtro, t_fim, self._tend)

    # --- salvar / carregar ------------------------------------------------
    def para_dict(self):
        d = {k: v for k, v in self.__dict__.items() if not k.startswith("_") and k not in ("traders", "ao_evento", "times")}
        d["traders"] = [dict(tr.para_dict(), desempenho=round(self.desempenho(tr), 2)) for tr in self.traders]
        d["times"] = [self.resumo_time(tm) for tm in self.times]
        if self.sprint:
            d["sprint_atual"] = self.resumo_sprint(self.salvo_em or self.sprint["inicio"])
        if self.futuros():
            d["aprendizado_resumo"] = self.resumo_aprendizado()
        return d

    @classmethod
    def de_dict(cls, d, cfg):
        o = cls.__new__(cls)
        o.__dict__.update(d)
        o.cfg = cfg
        o.traders = [Trader.de_dict(x) for x in d["traders"]]
        campos = ("id", "nome", "emoji", "inspiracao", "estrategia", "estrategia_nome", "params", "intervalo", "titular",
                  "aportes", "lucro_usado_bebes", "bonus_bebe1_pago", "curva", "nota_escola", "criado_em", "pontuacao", "lugar", "especial", "modo", "alavancagem", "confianca",
                  "membros", "preco_inicial", "caixa_time", "contratados", "demitidos")
        o.times = [{k: tm.get(k) for k in campos} for tm in d.get("times", [])]
        o.sprint = d.get("sprint")
        o.sprints = d.get("sprints", [])
        o._iniciar_temporarios()
        return o

    # --- utilidades -------------------------------------------------------
    def evento(self, t, quem, emoji, texto):
        e = {"t": t, "quem": quem.rotulo(self) if quem else "Agência", "time": quem.time if quem else None,
             "emoji": emoji, "texto": texto}
        self.eventos.append(e)
        self.eventos = self.eventos[-600:]
        if self.ao_evento:
            self.ao_evento(e)

    def time(self, time_id):
        return next(tm for tm in self.times if tm["id"] == time_id)

    def do_time(self, time_id):
        return [tr for tr in self.traders if tr.time == time_id]

    def aporte(self, trader, valor_usd):
        trader.caixa += valor_usd
        trader.capital_recebido = getattr(trader, "capital_recebido", 0.0) + valor_usd
        self.time(trader.time)["aportes"] += valor_usd
        self.aportes_ceo += valor_usd

    def patrimonio(self, time_id=None):
        """Traders + o caixa de contratação dos times (dinheiro da empresa que ainda não virou funcionário)."""
        caixas = sum(tm.get("caixa_time") or 0.0 for tm in self.times if time_id is None or tm["id"] == time_id)
        empresa = (getattr(self, "caixa_empresa", 0.0) or 0.0) if time_id is None else 0.0
        return sum(tr.patrimonio() for tr in self.traders if time_id is None or tr.time == time_id) + caixas + empresa

    # --- a empresa: metas de lucro, bônus, caixa do time e contratações -------------------------
    def _empresa(self):
        return self.cfg.get("empresa", {})

    def pagar_metas(self, tr, t):
        """A cada US$ 50 de lucro realizado (novo recorde), o funcionário fica com US$ 20 e manda US$ 30 pro caixa do time."""
        e = self._empresa()
        if not e.get("ativo"):
            return
        meta, fica, vai = e.get("meta_lucro_usd", 50), e.get("bonus_funcionario_usd", 20), e.get("para_caixa_do_time_usd", 30)
        marco = getattr(tr, "lucro_marco", 0.0)
        tm = self.time(tr.time)
        while tr.lucro_realizado - marco >= meta and tr.caixa >= vai:
            marco += meta
            tr.caixa -= vai
            tr.enviado_caixa = getattr(tr, "enviado_caixa", 0.0) + vai
            tm["caixa_time"] = (tm.get("caixa_time") or 0.0) + vai
            tr.metas_batidas = getattr(tr, "metas_batidas", 0) + 1
            tr.bonus_recebido = getattr(tr, "bonus_recebido", 0.0) + fica
            self.evento(t, tr, "💵", f"{tr.rotulo(self)} bateu a meta de US$ {meta:.0f}: ficou com US$ {fica:.0f} de bônus e mandou "
                                    f"US$ {vai:.0f} pro caixa do time ({tm['caixa_time']:.0f}/{e.get('custo_contratacao_usd', 500):.0f})")
        tr.lucro_marco = marco
        self._contratar(tm, t)

    @staticmethod
    def desempenho(tr):
        """Resultado do funcionário em % do dinheiro que ele recebeu (contando o que ele já mandou pro caixa do time)."""
        base = getattr(tr, "capital_recebido", 0.0) or 1000.0
        return (tr.patrimonio() + getattr(tr, "enviado_caixa", 0.0) - base) / base * 100

    def _para_empresa(self, tm, valor):
        """Dinheiro que sai do time pro caixa da empresa (não conta como prejuízo do time no ranking)."""
        self.caixa_empresa = (getattr(self, "caixa_empresa", 0.0) or 0.0) + valor
        tm["aportes"] -= valor

    def _contratar(self, tm, t):
        """Juntou US$ 500 no caixa do time: demite o pior, contrata 1 novo, o melhor ganha US$ 50,
        e o que sobrar no caixa do time vai pro caixa da empresa (a contagem zera)."""
        e = self._empresa()
        custo = e.get("custo_contratacao_usd", 500)
        if (tm.get("caixa_time") or 0) < custo:
            return
        membros = self.do_time(tm["id"])
        if not membros:
            return
        # 1) demite quem desempenhou pior (quem entrou há menos de N dias está em experiência e não sai)
        carencia = e.get("experiencia_dias", 7) * 86_400_000
        elegiveis = [m for m in membros if t - m.criado_em >= carencia] or membros
        pior = min(elegiveis, key=self.desempenho)
        d_pior = self.desempenho(pior)
        if pior.posicao or (getattr(pior, "grade_estado", None) or {}).get("lotes"):
            pior.encerrar(pior.ultimo_preco or (pior.posicao or {}).get("preco") or 0, t, self.cfg, self)
        sobra = max(0.0, pior.patrimonio())
        self.traders = [x for x in self.traders if x is not pior]
        self._para_empresa(tm, sobra)
        tm["demitidos"] = (tm.get("demitidos") or 0) + 1
        membros = [m for m in membros if m is not pior]
        # 2) contrata 1 (com os US$ 500 do caixa do time)
        moedas = list(dict.fromkeys(self.cfg["liga"]["moedas"] + e.get("moedas_novas", [])))
        uso = {p: sum(1 for m in membros if m.par == p) for p in moedas}
        par = min(moedas, key=lambda p: (uso[p], moedas.index(p)))
        base = next((m for m in membros if m.tipo != "contratado"), membros[0] if membros else pior)
        if tm.get("membros"):   # Comitê: reveza as estratégias
            est_id = tm["membros"][(tm.get("contratados") or 0) % len(tm["membros"])]
            params = next((m.params for m in membros if m.estrategia == est_id), tm["params"])
        else:
            est_id, params = base.estrategia, base.params
        n = uso[par] + 1
        nome = moeda(par) + (f" {POR_ID[est_id].emoji}" if tm.get("membros") else "") + (f" {n}" if n > 1 else "")
        novo = Trader(nome, "🧑‍💼", par, 0.0, "contratado", t, tm["id"], est_id, params)
        novo.caixa = novo.capital_recebido = custo
        novo.ultimo_preco = self.ultimo_preco.get(par)
        novo.alavancagem = base.alavancagem
        self.traders.append(novo)
        tm["contratados"] = (tm.get("contratados") or 0) + 1
        resto = tm["caixa_time"] - custo
        tm["caixa_time"] = 0.0
        if resto > 0:
            self._para_empresa(tm, resto)
        # 3) o melhor funcionário ganha US$ 50 (pago pelo caixa da empresa; se não tiver, pelo CEO)
        premio = e.get("premio_melhor_usd", 50)
        melhor = max(membros, key=self.desempenho) if membros else None
        if melhor and premio:
            if (getattr(self, "caixa_empresa", 0.0) or 0) >= premio:
                self.caixa_empresa -= premio
                melhor.caixa += premio
                tm["aportes"] += premio
            else:
                self.aporte(melhor, premio)
            melhor.premios = getattr(melhor, "premios", 0) + 1
        self.evento(t, novo, "🤝", f"{tm['emoji']} {tm['nome']} juntou US$ {custo:.0f} e contratou {nome}. "
                                  f"👋 Demitido: {pior.nome} (pior desempenho, {d_pior:+.1f}%) — os US$ {sobra:.0f} dele foram pro caixa da empresa."
                                  + (f" ⭐ {melhor.nome} foi o melhor ({self.desempenho(melhor):+.1f}%) e ganhou US$ {premio:.0f}." if melhor and premio else "")
                                  + (f" Sobra de US$ {resto:.0f} foi pro caixa da empresa." if resto > 0.005 else ""))

    def chaves(self):
        ks = {tr.chave for tr in self.traders}
        if self.futuros():  # velas extras: filtro de tendência da grade e o regime de longo prazo
            reg = self.cfg.get("futuros", {}).get("regime", {"intervalo": "1d"})["intervalo"]
            for tr in self.traders:
                filtro = tr.params.get("filtro")
                if filtro:
                    ks.add(f"{tr.par}@{filtro['intervalo']}")
                if tr.estrategia != "grade":
                    ks.add(f"{tr.par}@{reg}")
        return sorted(ks)

    def pares(self):
        return sorted({tr.par for tr in self.traders})

    def atualizar_precos(self, precos):
        for par, preco in precos.items():
            self.ultimo_preco[par] = preco
        for tr in self.traders:
            if tr.par in precos:
                tr.ultimo_preco = precos[tr.par]

    def marcar_curva(self, t):
        if self.curva and t - self.curva[-1][0] < 15 * 60_000:
            return
        self.curva.append([t, round(self.patrimonio(), 4), round(self.aportes_ceo, 4)])
        for tm in self.times:
            if tm.get("preco_inicial") is None:
                tm["preco_inicial"] = {}
            pi = tm["preco_inicial"]
            for tr in self.do_time(tm["id"]):
                if tr.par not in pi and self.ultimo_preco.get(tr.par):
                    pi[tr.par] = self.ultimo_preco[tr.par]
        if self.sprint is not None:
            ps = self.sprint.setdefault("precos", {})
            for par, px in self.ultimo_preco.items():
                ps.setdefault(par, px)
        self._amostrar_sprint()
        for tm in self.times:
            tm["curva"].append([t, round(self.patrimonio(tm["id"]), 4), round(tm["aportes"], 4)])
            if len(tm["curva"]) > 4000:
                tm["curva"] = tm["curva"][::2]
        if len(self.curva) > 4000:
            self.curva = self.curva[::2]

    # --- liga ---------------------------------------------------------------
    def nova_temporada(self, escolhidos, t):
        """escolhidos = lista de resultados da escola (id, nome, emoji, inspiracao, params_atuais, nota)."""
        numero = (self.temporada or {}).get("numero", 0) + 1
        self.times, self.traders, self.curva, self.aportes_ceo = [], [], [], 0.0
        fut = self.cfg.get("futuros", {})
        self.mercado = "futuros" if fut.get("ativo") else "spot"
        lmax = fut.get("alavancagem_max", 10) if self.futuros() else 1
        moedas = self.cfg["liga"]["moedas"]
        capital = self.cfg["liga"]["capital_por_trader_usd"]
        for k, r in enumerate(escolhidos):
            if r.get("comite"):
                self._criar_comite(r, t, lmax, moedas, capital)
                continue
            est = POR_ID[r["id"]]
            tm = {"id": r["id"], "nome": NOMES_TIME.get(r["id"], "Time " + est.nome),
                  "emoji": est.emoji, "inspiracao": r["inspiracao"], "estrategia": r["id"], "estrategia_nome": est.nome,
                  "params": r["params_atuais"], "intervalo": r["params_atuais"]["intervalo"], "titular": False,
                  "aportes": 0.0, "lucro_usado_bebes": 0.0, "bonus_bebe1_pago": False, "curva": [],
                  "nota_escola": r.get("nota"), "criado_em": t, "pontuacao": 0.0, "lugar": None,
                  "alavancagem": lmax, "confianca": confianca_da_escola(r.get("oos")) if self.futuros() else 1.0,
                  "preco_inicial": {}}
            self.times.append(tm)
            for par in moedas:
                tr = Trader(moeda(par), self.cfg["liga"].get("emoji_trader", "🤖"), par, 0.0, "trader", t,
                            tm["id"], r["id"], r["params_atuais"])
                tr.ultimo_preco = self.ultimo_preco.get(par)
                tr.alavancagem = tm["alavancagem"]
                self.traders.append(tr)
                self.aporte(tr, capital)
        self.times[0]["titular"] = True  # na semana 1, o titular é o de melhor nota na escola
        self.adicionar_mesa_rapida(t)
        for k, tm in enumerate(self.disputando(), 1):
            tm["lugar"] = k
        # 1ª rodada: a primeira segunda-feira depois de pelo menos 1 semana inteira de jogo
        self.temporada = {"numero": numero, "inicio": t, "proxima_rodada": proxima_segunda(t + 6 * 86_400_000),
                          "titular": self.times[0]["id"], "rodadas": []}
        self.abrir_sprint(t)
        mercado = f" em FUTUROS (LONG e SHORT, alavancagem por julgamento até {lmax}x)" if self.futuros() else ""
        self.evento(t, None, "🏁", f"Começou a temporada {numero}{mercado}! Titular da 1ª semana: {self.times[0]['emoji']} {self.times[0]['nome']}")

    def _criar_comite(self, r, t, lmax, moedas, capital):
        """Time Comitê: as N melhores estratégias dividindo o mesmo dinheiro (um robô por estratégia e moeda)."""
        membros = r["comite"]
        nomes = " + ".join(NOMES_TIME.get(m["id"], m["nome"]).replace("Time ", "") for m in membros)
        tm = {"id": "comite", "nome": "Time Comitê", "emoji": "🤝", "inspiracao": "as melhores da escola juntas",
              "estrategia": membros[0]["id"], "estrategia_nome": f"comitê: {nomes}", "params": membros[0]["params_atuais"],
              "intervalo": "/".join(sorted({m["params_atuais"]["intervalo"] for m in membros})), "titular": False,
              "aportes": 0.0, "lucro_usado_bebes": 0.0, "bonus_bebe1_pago": False, "curva": [], "nota_escola": r.get("nota"),
              "criado_em": t, "pontuacao": 0.0, "lugar": None, "alavancagem": lmax, "preco_inicial": {},
              "confianca": round(sum(confianca_da_escola(m.get("oos")) for m in membros) / len(membros), 2) if self.futuros() else 1.0,
              "membros": [m["id"] for m in membros]}
        self.times.append(tm)
        for par in moedas:
            for m in membros:
                est = POR_ID[m["id"]]
                tr = Trader(f"{moeda(par)} {est.emoji}", self.cfg["liga"].get("emoji_trader", "🤖"), par, 0.0, "trader", t,
                            "comite", m["id"], m["params_atuais"])
                tr.ultimo_preco = self.ultimo_preco.get(par)
                tr.alavancagem = lmax
                self.traders.append(tr)
                self.aporte(tr, capital / len(membros))

    def adicionar_mesa_rapida(self, t):
        """Mesa Rápida: estagiários com velas curtas, FORA da disputa (nunca viram titular, sem bebês)."""
        mr = self.cfg["liga"].get("mesa_rapida", {})
        modo = mr.get("modo", "grade") if mr.get("ativo") else None
        atual = next((tm for tm in self.times if tm.get("especial")), None)
        if atual and atual.get("modo", "estagiarios") != modo:
            self.remover_mesa(t)
            atual = None
        if not modo or atual:
            return
        if modo == "grade":
            gr = dict(mr.get("grade", {}))
            fut = self.cfg.get("futuros", {})
            alav = fut.get("alavancagem_mesa", 5) if self.futuros() else 1
            if self.futuros():
                gr.update(fut.get("grade", {}))
            nome_est = f"grade de {gr.get('degrau', 0.005):.1%} em ±{gr.get('faixa', 0.2):.0%}"
            if self.futuros():
                nome_est = f"grade {alav}x a favor da tendência de 4h, degrau de {gr.get('degrau', 0.008):.1%}"
            tm = {"id": "rapida", "nome": "Mesa de Grade", "emoji": "🧮", "inspiracao": "robôs de grade (grid)", "modo": "grade",
                  "alavancagem": alav, "estrategia": "grade", "estrategia_nome": nome_est,
                  "params": {}, "intervalo": gr.get("intervalo", "5m"), "titular": False, "aportes": 0.0, "lucro_usado_bebes": 0.0,
                  "bonus_bebe1_pago": True, "curva": [], "nota_escola": None, "criado_em": t, "pontuacao": 0.0, "lugar": None, "especial": True}
            self.times.append(tm)
            params = {"intervalo": gr.get("intervalo", "5m"), "degrau": gr.get("degrau", 0.005), "faixa": gr.get("faixa", 0.20)}
            if self.futuros() and gr.get("filtro"):
                params["filtro"] = gr["filtro"]
            for par in gr.get("moedas", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]):
                tr = Trader(moeda(par), "🤖", par, 0.0, "trader", t, "rapida", "grade", params)
                tr.ultimo_preco = self.ultimo_preco.get(par)
                tr.alavancagem = alav
                self.traders.append(tr)
                self.aporte(tr, gr.get("capital_por_trader_usd", 250))  # cada degrau precisa de ≥ US$ 5 (mínimo da Binance)
            self.evento(t, None, "🧮", "Chegou a Mesa de Grade: robôs que operam em degraus" + (f", {alav}x, LONG ou SHORT conforme a tendência" if self.futuros() else "") + " (fora da disputa)")
            return
        tm = {"id": "rapida", "nome": "Mesa Rápida", "emoji": "⚡", "inspiracao": "estagiários (velas de 5 e 15 min)", "modo": "estagiarios",
              "estrategia": None, "estrategia_nome": "várias, velas curtas", "params": {}, "intervalo": "5–15m", "titular": False,
              "aportes": 0.0, "lucro_usado_bebes": 0.0, "bonus_bebe1_pago": True, "curva": [], "nota_escola": None,
              "criado_em": t, "pontuacao": 0.0, "lugar": None, "especial": True}
        self.times.append(tm)
        for e in mr.get("estagiarios", []):
            est = POR_ID[e["estrategia"]]
            params = dict(est.params); params.update(e.get("params", {})); params["intervalo"] = e["intervalo"]
            tr = Trader(moeda(e["par"]), "🤖", e["par"], 0.0, "trader", t, "rapida", e["estrategia"], params)
            tr.ultimo_preco = self.ultimo_preco.get(e["par"])
            if self.futuros():
                tr.alavancagem = self.cfg.get("futuros", {}).get("alavancagem_mesa", 5)
            self.traders.append(tr)
            self.aporte(tr, mr.get("capital_por_trader_usd", 100))
        self.evento(t, None, "⚡", "Chegaram os estagiários da Mesa Rápida (velas curtas, fora da disputa)")

    # ------------------------------------------------------------------ sprints
    def _segurar(self, tid, base):
        """Quanto teria rendido só COMPRAR E SEGURAR as moedas do time desde `base` (preços), em %."""
        pares = sorted({tr.par for tr in self.do_time(tid)})
        rs = [(self.ultimo_preco[p] / base[p] - 1) * 100 for p in pares if base.get(p) and self.ultimo_preco.get(p)]
        return round(sum(rs) / len(rs), 2) if rs else None

    def _foto(self):
        f = {}
        for tm in self.times:
            trs = self.do_time(tm["id"])
            patr = self.patrimonio(tm["id"])
            f[tm["id"]] = {"lucro": patr - tm["aportes"], "patr": patr,
                           "taxas": sum(getattr(t, "taxas_pagas", 0.0) for t in trs),
                           "volume": sum(getattr(t, "volume", 0.0) for t in trs),
                           "vit": sum(t.vitorias for t in trs), "der": sum(t.derrotas for t in trs),
                           "funding": sum(getattr(t, "funding_pago", 0.0) for t in trs),
                           "liq": sum(getattr(t, "liquidacoes", 0) for t in trs)}
        return f

    def abrir_sprint(self, t):
        n = self.sprints[-1]["numero"] + 1 if self.sprints else 1
        duracao = self.cfg["liga"].get("sprint", {}).get("duracao", "semana")
        if duracao == "dia":
            fim = proxima_meia_noite(t)
        else:
            fim = self.temporada["proxima_rodada"] if self.temporada else t + SEMANA
        self.sprint = {"numero": n, "inicio": t, "fim": fim, "duracao": duracao, "base": self._foto(), "exp": {}, "amostras": 0,
                       "pico": {}, "queda": {}, "precos": dict(self.ultimo_preco)}

    def _amostrar_sprint(self):
        sp = self.sprint
        if not sp:
            return
        sp["amostras"] += 1
        for tm in self.times:
            tid = tm["id"]
            patr = self.patrimonio(tid)
            dentro = sum(abs(t.posicao["qtd"]) * (t.ultimo_preco or t.posicao["preco"]) for t in self.do_time(tid) if t.posicao)
            sp["exp"][tid] = sp["exp"].get(tid, 0.0) + (dentro / patr if patr > 0 else 0.0)
            base = sp["base"].get(tid) or {"lucro": patr - tm["aportes"], "patr": patr}
            lucro = (patr - tm["aportes"]) - base["lucro"]
            sp["pico"][tid] = max(sp["pico"].get(tid, 0.0), lucro)
            queda = (lucro - sp["pico"][tid]) / (base["patr"] or 1) * 100
            sp["queda"][tid] = min(sp["queda"].get(tid, 0.0), queda)

    def resumo_sprint(self, t):
        sp = self.sprint
        agora = self._foto()
        metas_cfg = self.cfg["liga"].get("sprint", {}).get("metas", {})
        linhas = []
        for tm in self.times:
            tid = tm["id"]
            a = agora[tid]
            b = sp["base"].get(tid) or dict(a, lucro=a["lucro"], taxas=a["taxas"], volume=a["volume"], vit=a["vit"], der=a["der"])
            cap = b["patr"] or a["patr"] or 1
            lucro = a["lucro"] - b["lucro"]
            taxas = a["taxas"] - b["taxas"]
            ops = (a["vit"] - b["vit"]) + (a["der"] - b["der"])
            funding = a.get("funding", 0.0) - b.get("funding", 0.0)
            liq = a.get("liq", 0) - b.get("liq", 0)
            linhas.append({"id": tid, "nome": tm["nome"], "emoji": tm["emoji"], "especial": bool(tm.get("especial")),
                           "lucro": round(lucro, 4), "lucro_pct": round(lucro / cap * 100, 3), "taxas": round(taxas, 4),
                           "bruto": round(lucro + taxas, 4), "volume": round(a["volume"] - b["volume"], 2),
                           "giro": round((a["volume"] - b["volume"]) / cap, 3), "operacoes": ops,
                           "vitorias": a["vit"] - b["vit"], "derrotas": a["der"] - b["der"],
                           "exposicao_pct": round(sp["exp"].get(tid, 0.0) / max(sp["amostras"], 1) * 100, 1),
                           "queda_pct": round(sp["queda"].get(tid, 0.0), 2), "funding": round(funding, 4),
                           "liquidacoes": liq, "alavancagem": tm.get("alavancagem"),
                           "segurar_pct": self._segurar(tid, sp.get("precos") or {})})
        principais = [x for x in linhas if not x["especial"]]
        cap_total = sum((sp["base"].get(x["id"]) or {}).get("patr", 0) or 1 for x in principais) or 1

        def soma(campo, lista=principais):
            return sum(x[campo] for x in lista)
        total = {"lucro": round(soma("lucro"), 4), "lucro_pct": round(soma("lucro") / cap_total * 100, 3),
                 "taxas": round(soma("taxas"), 4), "bruto": round(soma("bruto"), 4), "volume": round(soma("volume"), 2),
                 "giro": round(soma("volume") / cap_total, 3), "operacoes": soma("operacoes"),
                 "vitorias": soma("vitorias"), "derrotas": soma("derrotas"),
                 "exposicao_pct": round(sum(x["exposicao_pct"] for x in principais) / max(len(principais), 1), 1),
                 "queda_pct": min([x["queda_pct"] for x in principais] or [0]),
                 "funding": round(soma("funding"), 4), "liquidacoes": soma("liquidacoes"),
                 "operacoes_agencia": soma("operacoes", linhas)}
        fechadas = [o for tr in self.traders for o in tr.trades if o["t_saida"] >= sp["inicio"]]
        total["lucro_medio_op"] = round(sum(o["lucro"] for o in fechadas) / len(fechadas), 4) if fechadas else None
        rs = [o["r"] for o in fechadas if o.get("r") is not None]
        total["r_medio"] = round(sum(rs) / len(rs), 2) if rs else None
        principais_ids = {x["id"] for x in principais}
        segs = [x["segurar_pct"] for x in linhas if x["id"] in principais_ids and x["segurar_pct"] is not None]
        total["segurar_pct"] = round(sum(segs) / len(segs), 2) if segs else None
        metas = []
        if "lucro_medio_por_operacao_min" in metas_cfg:
            v = total["lucro_medio_op"]
            metas.append({"meta": f"lucro médio por operação (depois das taxas) ≥ US$ {metas_cfg['lucro_medio_por_operacao_min']:.2f}",
                          "valor": "sem operações fechadas" if v is None else f"US$ {v:+.3f}" + (f" ({total['r_medio']:+.2f}R)" if total["r_medio"] is not None else ""),
                          "ok": v is not None and v >= metas_cfg["lucro_medio_por_operacao_min"]})
        if "bater_segurar" in metas_cfg and metas_cfg["bater_segurar"] and total["segurar_pct"] is not None:
            metas.append({"meta": "times melhor que comprar e segurar as mesmas moedas", "valor": f"{total['lucro_pct']:+.2f}% vs {total['segurar_pct']:+.2f}%",
                          "ok": total["lucro_pct"] >= total["segurar_pct"]})
        if "operacoes_min" in metas_cfg:
            metas.append({"meta": f"pelo menos {metas_cfg['operacoes_min']} operações (agência toda)", "valor": str(total["operacoes_agencia"]),
                          "ok": total["operacoes_agencia"] >= metas_cfg["operacoes_min"]})
        if "lucro_min_pct" in metas_cfg:
            metas.append({"meta": f"resultado dos times ≥ {metas_cfg['lucro_min_pct']:+.1f}%", "valor": f"{total['lucro_pct']:+.2f}%",
                          "ok": total["lucro_pct"] >= metas_cfg["lucro_min_pct"]})
        if "taxas_max_pct_do_bruto" in metas_cfg:
            pct_t = total["taxas"] / total["bruto"] * 100 if total["bruto"] > 0 else (0 if total["taxas"] == 0 else 999)
            metas.append({"meta": f"taxas ≤ {metas_cfg['taxas_max_pct_do_bruto']}% do lucro bruto",
                          "valor": "sem taxas" if total["taxas"] == 0 else (f"{pct_t:.0f}%" if pct_t < 999 else "lucro bruto negativo"),
                          "ok": pct_t <= metas_cfg["taxas_max_pct_do_bruto"]})
        if "queda_max_pct" in metas_cfg:
            metas.append({"meta": f"nenhum time cair mais de {metas_cfg['queda_max_pct']}%", "valor": f"{total['queda_pct']:.2f}%",
                          "ok": total["queda_pct"] >= -metas_cfg["queda_max_pct"]})
        if "liquidacoes_max" in metas_cfg and self.futuros():
            liq_tot = soma("liquidacoes", linhas)
            metas.append({"meta": f"no máximo {metas_cfg['liquidacoes_max']} liquidação(ões)", "valor": str(liq_tot),
                          "ok": liq_tot <= metas_cfg["liquidacoes_max"]})
        dias = max((t - sp["inicio"]) / 86_400_000, 0)
        return {"numero": sp["numero"], "inicio": sp["inicio"], "fim": sp["fim"], "dias": round(dias, 1),
                "duracao": sp.get("duracao", "semana"), "mercado": getattr(self, "mercado", "spot"),
                "times": linhas, "total": total, "metas": metas, "diagnosticos": self._diagnosticos(linhas, total)}

    def _diagnosticos(self, linhas, total):
        d = []
        principais = [x for x in linhas if not x["especial"]]
        if total["operacoes"] == 0:
            d.append("Os times não fecharam nenhuma operação: o mercado não deu sinal de tendência. Isso é esperado das "
                     "estratégias lentas — pra girar mais sem perder assertividade, o caminho é dar mais moedas pra cada time.")
        if total["exposicao_pct"] < 20:
            d.append(f"O dinheiro dos times ficou parado em média {100 - total['exposicao_pct']:.0f}% do tempo.")
        if total["bruto"] > 0 and total["taxas"] > 0.3 * total["bruto"]:
            d.append(f"As taxas comeram {total['taxas'] / total['bruto'] * 100:.0f}% do lucro bruto (US$ {total['taxas']:.2f}).")
        elif total["bruto"] <= 0 and total["taxas"] > 0:
            d.append(f"Os times perderam US$ {abs(total['bruto']):.2f} antes das taxas e ainda pagaram US$ {total['taxas']:.2f} de taxa.")
        if total["operacoes"] >= 5:
            acerto = total["vitorias"] / total["operacoes"] * 100
            if acerto < 35:
                d.append(f"Acerto de {acerto:.0f}% — normal pra tendência, desde que os ganhos sejam bem maiores que as perdas.")
        if total.get("liquidacoes"):
            d.append(f"{total['liquidacoes']} liquidação(ões) nos times: a alavancagem foi maior que o stop aguenta. "
                     "Menos alavancagem ou menos margem por operação (futuros.margem_por_operacao) evita isso.")
        if abs(total.get("funding", 0)) >= 0.01:
            d.append(f"Funding: os times {'pagaram' if total['funding'] > 0 else 'receberam'} US$ {abs(total['funding']):.2f} "
                     "(comprado paga e vendido recebe quando o mercado está otimista).")
        com_ops = [x for x in principais if x["operacoes"] > 0 or abs(x["lucro"]) > 0.01]
        if len(com_ops) >= 2:
            m = max(com_ops, key=lambda x: x["lucro_pct"]); p = min(com_ops, key=lambda x: x["lucro_pct"])
            d.append(f"Melhor da sprint: {m['emoji']} {m['nome']} ({m['lucro_pct']:+.2f}%). Pior: {p['emoji']} {p['nome']} ({p['lucro_pct']:+.2f}%).")
        for x in linhas:
            if x["especial"] and x["operacoes"] > 0:
                d.append(f"Mesa Rápida: {x['operacoes']} operações, girou US$ {x['volume']:.0f} e pagou US$ {x['taxas']:.2f} de taxa — "
                         f"resultado {x['lucro_pct']:+.2f}% ({'as taxas pesaram' if x['taxas'] > abs(x['bruto']) else 'resultado veio do mercado'}).")
        return d

    def fechar_sprint(self, t):
        if not self.sprint:
            self.abrir_sprint(t)
            return None
        r = self.resumo_sprint(t)
        r["fim"] = t
        r["temporada"] = (self.temporada or {}).get("numero")
        self.sprints.append(r)
        self.sprints = self.sprints[-90:]
        tot = r["total"]
        self.evento(t, None, "🏃", f"Sprint {r['numero']} fechada: {tot.get('operacoes_agencia', tot['operacoes'])} operações, resultado dos times {tot['lucro_pct']:+.2f}%, "
                                  f"taxas US$ {tot['taxas']:.2f}. Veja a retrospectiva na aba Sprints")
        self.abrir_sprint(t)
        return r

    def remover_mesa(self, t):
        """Fecha as posições da mesa especial a preço de mercado e tira ela do escritório."""
        tm = next((x for x in self.times if x.get("especial")), None)
        if not tm:
            return
        for tr in self.do_time(tm["id"]):
            if tr.posicao:
                tr.encerrar(tr.ultimo_preco or tr.posicao["preco"], t, self.cfg, self)
        resultado = self.patrimonio(tm["id"]) - tm["aportes"]
        self.aportes_ceo -= tm["aportes"]
        self.traders = [x for x in self.traders if x.time != tm["id"]]
        self.times = [x for x in self.times if x is not tm]
        self.evento(t, None, "👋", f"A {tm['nome']} foi encerrada com resultado de US$ {resultado:+.2f}")

    def disputando(self):
        return [tm for tm in self.times if not tm.get("especial")]

    def pontuar(self, tm, t):
        """Retorno das últimas N semanas menos metade da maior queda no período (em %)."""
        semanas = self.cfg["liga"].get("semanas_para_pontuar", 4)
        curva = [x for x in tm["curva"] if x[0] >= t - semanas * SEMANA]
        if len(curva) < 2:
            return 0.0, 0.0, 0.0
        lucro = [p - a for _, p, a in curva]
        base = curva[0][1] or 1.0
        ret = (lucro[-1] - lucro[0]) / base * 100
        pico, queda = lucro[0], 0.0
        for x in lucro:
            pico = max(pico, x)
            queda = min(queda, (x - pico) / base * 100)
        return round(ret + 0.5 * queda, 3), round(ret, 2), round(queda, 2)

    def rodada(self, t):
        ranking = []
        for tm in self.times:
            if tm.get("especial"):
                tm["pontuacao"] = self.pontuar(tm, t)[0]
        for tm in self.disputando():
            pts, ret, queda = self.pontuar(tm, t)
            tm["pontuacao"] = pts
            ranking.append({"id": tm["id"], "pontuacao": pts, "retorno_pct": ret, "queda_pct": queda})
        ranking.sort(key=lambda x: (x["pontuacao"], self.time(x["id"]).get("nota_escola") or 0), reverse=True)
        for k, r in enumerate(ranking, 1):
            self.time(r["id"])["lugar"] = k
        vencedor = ranking[0]["id"]
        antigo = self.temporada["titular"]
        for tm in self.times:
            tm["titular"] = tm["id"] == vencedor and not tm.get("especial")
        self.temporada["titular"] = vencedor
        self.temporada["rodadas"].append({"t": t, "vencedor": vencedor, "ranking": ranking})
        self.temporada["rodadas"] = self.temporada["rodadas"][-60:]
        self.temporada["proxima_rodada"] = proxima_segunda(t)
        v = self.time(vencedor)
        if vencedor == antigo:
            self.evento(t, None, "🏆", f"{v['emoji']} {v['nome']} continua TITULAR ({ranking[0]['pontuacao']:+.2f} pts)")
        else:
            self.evento(t, None, "🏆", f"{v['emoji']} {v['nome']} é o novo TITULAR ({ranking[0]['pontuacao']:+.2f} pts)")

    def resumo_time(self, tm):
        tid = tm["id"]
        patr = self.patrimonio(tid)
        t = self.salvo_em or (self.curva[-1][0] if self.curva else tm["criado_em"])
        pts, ret4, queda4 = self.pontuar(tm, t)
        realizado = sum(tr.lucro_realizado for tr in self.do_time(tid))
        meta = self.cfg["bebes"]["lucro_brl_por_bebe"]
        juntado = max(0.0, (realizado - tm["lucro_usado_bebes"]) * self.cotacao_brl)
        e = self._empresa()
        membros = self.do_time(tid)
        destaque = max(membros, key=self.desempenho, default=None)
        abertos = [tr.posicao for tr in self.do_time(tid) if tr.posicao and tr.posicao.get("alavancagem")]
        return dict(tm, patrimonio=round(patr, 4), resultado_pct=round((patr / tm["aportes"] - 1) * 100, 3) if tm["aportes"] else 0.0,
                    segurar_pct=self._segurar(tid, tm.get("preco_inicial") or {}),
                    alavancagem_media=round(sum(p["alavancagem"] for p in abertos) / len(abertos), 1) if abertos else None,
                    confianca_agora=self.confianca_viva(tid) if not tm.get("especial") else None,
                    caixa_time=round(tm.get("caixa_time") or 0.0, 2), contratados=tm.get("contratados") or 0,
                    demitidos=tm.get("demitidos") or 0,
                    pior=({"nome": p_.nome, "desempenho": round(self.desempenho(p_), 2)} if (p_ := min(membros, key=self.desempenho, default=None)) else None),
                    funcionarios=len(membros), max_funcionarios=e.get("max_funcionarios_por_time", 15),
                    meta_contratacao_pct=round(min(100.0, (tm.get("caixa_time") or 0) / e.get("custo_contratacao_usd", 500) * 100), 1),
                    destaque=({"nome": destaque.nome, "lucro": round(destaque.lucro_realizado, 2), "desempenho": round(self.desempenho(destaque), 2),
                               "metas": getattr(destaque, "metas_batidas", 0)} if destaque else None),
                    pontuacao_agora=pts, retorno_4s_pct=ret4, queda_4s_pct=queda4,
                    bebes=sum(1 for tr in self.do_time(tid) if tr.tipo == "bebe"),
                    meta_bebe_pct=round(min(100.0, juntado / meta * 100), 1), lucro_bebe_brl=round(juntado, 2))

    # --- velas ------------------------------------------------------------
    def aquecer(self, chave, vela):
        b = self._buf.setdefault(chave, {"t": [], "o": [], "h": [], "l": [], "c": [], "v": []})
        if b["t"] and vela["t"] <= b["t"][-1]:
            return False
        for k in ("t", "o", "h", "l", "c", "v"):
            b[k].append(vela[k])
            if len(b[k]) > TAMANHO_BUFFER:
                del b[k][0]
        self.ultimo_t[chave] = max(self.ultimo_t.get(chave, 0), vela["t"])
        return True

    def sincronizar(self, chave, t):
        """Trader recém-criado entra no estado que a estratégia dele teria HOJE (como um trader
        profissional faz ao ligar um sistema), em vez de esperar dias pelo próximo cruzamento."""
        if not self.cfg["liga"].get("sincronizar_ao_comecar", True):
            return
        v = self._buf.get(chave)
        if not v or len(v["c"]) < 60:
            return
        n, preco = len(v["c"]), v["c"][-1]
        for tr in self.traders:
            if tr.chave != chave or tr.posicao or tr.trades or getattr(tr, "sincronizado", False):
                continue
            tr.sincronizado = True
            est, p = POR_ID[tr.estrategia], tr.params
            if est.tipo == "grade":
                continue
            d = est.calcular(v, p)
            if self.futuros():
                ve = espelho(v) if self.cfg.get("futuros", {}).get("vender_a_descoberto", True) else None
                de = est.calcular(ve, p) if ve is not None else None
                tr.sincronizar_fut(est, v, d, ve, de, t, self.cfg, self)
                tr.gatilho_fut(est, d, v, de, ve, n - 1)
                continue
            tr.atualizar_gatilho(est, d, v, n - 1)
            if est.tipo == "peso":
                w = est.peso(d, v, n - 1, p)
                if w > 0:
                    tr._abrir(w * tr.caixa, preco, t, None, None, self.cfg, self, sincronizando=True)
                tr.atualizar_gatilho(est, d, v, n - 1)
                continue
            pos = None
            for i in range(1, n):
                if pos:
                    if checar_saida(est, d, v, i, p, pos):
                        pos = None
                elif pode_entrar(est, d, v, i, p):
                    stop, alvo = niveis_de_entrada(d, i, p, v["c"][i])
                    pos = {"preco": v["c"][i], "stop": stop, "alvo": alvo, "barras": 0, "maxc": v["c"][i]}
            if pos and preco > pos["stop"] and (not pos["alvo"] or preco < pos["alvo"]):
                tr._abrir(tr.caixa * fracao_entrada(d, n - 1, p), preco, t, pos["stop"], pos["alvo"], self.cfg, self, sincronizando=True)
                if tr.posicao:
                    tr.posicao.update(barras=pos["barras"], maxc=max(pos["maxc"], preco))
            tr.atualizar_gatilho(est, d, v, n - 1)

    def processar_vela(self, chave, vela):
        if vela["t"] <= self.ultimo_t.get(chave, 0) or not self.aquecer(chave, vela):
            return
        v = self._buf[chave]
        self.ultimo_preco[chave.split("@")[0]] = vela["c"]
        cache = {}
        shorts = self.futuros() and self.cfg.get("futuros", {}).get("vender_a_descoberto", True)
        ve = None
        for tr in list(self.traders):
            if tr.chave != chave:
                continue
            est = POR_ID[tr.estrategia]
            k = (tr.estrategia, json.dumps(tr.params, sort_keys=True))
            if k not in cache:
                if est.tipo == "grade":
                    cache[k] = ({}, None)
                else:
                    if shorts and ve is None:
                        ve = espelho(v)
                    cache[k] = (est.calcular(v, tr.params), est.calcular(ve, tr.params) if shorts else None)
            d, de = cache[k]
            tr.processar(v, d, self.cfg, self, ve if shorts else None, de)
            self.pagar_metas(tr, vela["t"])
        for tm in self.disputando():
            self._checar_bebes(tm, vela["t"])

    def _checar_bebes(self, tm, t):
        b = self.cfg["bebes"]
        if not b.get("ativo", True):
            return
        brl = self.cotacao_brl
        membros = self.do_time(tm["id"])
        bebes = [x for x in membros if x.tipo == "bebe"]
        custo_usd = b["lucro_brl_por_bebe"] / brl
        disponivel = sum(x.lucro_realizado for x in membros) - tm["lucro_usado_bebes"]

        if len(bebes) < b["max_bebes_por_time"] and disponivel >= custo_usd:
            livres = sorted([x for x in membros if not x.posicao], key=lambda x: -x.caixa)
            if sum(x.caixa for x in livres) >= custo_usd:
                falta = custo_usd
                for x in livres:
                    tira = min(x.caixa, falta)
                    x.caixa -= tira
                    falta -= tira
                    if falta <= 1e-9:
                        break
                n = len(bebes) + 1
                par = b["moedas"][(n - 1) % len(b["moedas"])]
                bebe = Trader(f"Bebê {moeda(par)}", "👶", par, custo_usd, "bebe", t, tm["id"], tm["estrategia"], tm["params"])
                bebe.ultimo_preco = self.ultimo_preco.get(par)
                bebe.alavancagem = tm.get("alavancagem") or 1
                self.traders.append(bebe)
                tm["lucro_usado_bebes"] += custo_usd
                self.evento(t, bebe, "🍼", f"Nasceu um bebê no {tm['nome']}! Vai operar {moeda(par)}")

        bonus = b.get("bonus_ceo_brl", 0)
        if bonus and not tm["bonus_bebe1_pago"] and bebes:
            if bebes[0].lucro_realizado * brl >= b["lucro_brl_por_bebe"]:
                tm["bonus_bebe1_pago"] = True
                for x in membros:
                    self.aporte(x, bonus / brl)
                self.evento(t, None, "🎉", f"Bônus do CEO: R$ {bonus:.0f} pra cada trader do {tm['nome']}")
