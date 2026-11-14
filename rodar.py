"""Agência de Trade — liga de 5 times de robôs de cripto SIMULADOS, Escola de Traders e o Claude como gerente.

Comandos:
  python rodar.py              menu
  python rodar.py escola       a Escola de Traders testa todos os alunos (walk-forward) e gera o boletim
  python rodar.py simular      liga a agência ao vivo (dinheiro de mentira) + escritório e painel
  python rodar.py painel       só abre o escritório/painel
  python rodar.py zerar        apaga a simulação e começa do zero
"""
import argparse
import json
import os
import queue
import shutil
import sys
import threading
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import escola as escola_mod
import gerente
import mercado
import painel
import sincronia
import operacao_real
from motor import Agencia, Trader, hhmm, moeda

AQUI = Path(__file__).resolve().parent
DADOS = AQUI / "dados"
ARQ_SIM = DADOS / "simulacao.json"


def _mesclar(base, extra):
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _mesclar(base[k], v)
        else:
            base[k] = v
    return base


TAXAS_CORRETORA = {   # futuros USDT-M, nível básico (conta comum)
    "binance": {"taxa_maker": 0.0002, "taxa_taker": 0.0005, "pagar_taxas_com_bnb": True},
    "bybit": {"taxa_maker": 0.0002, "taxa_taker": 0.00055, "pagar_taxas_com_bnb": False},
    "bitget": {"taxa_maker": 0.0002, "taxa_taker": 0.0006, "pagar_taxas_com_bnb": False},
}


def carregar_config():
    """Padrões em config.padrao.json (vem nas atualizações) + o que você mudar em config.json (só seu)."""
    cfg = json.loads((AQUI / "config.padrao.json").read_text(encoding="utf-8"))
    pessoal = AQUI / "config.json"
    meu = {}
    if pessoal.exists():
        try:
            meu = json.loads(pessoal.read_text(encoding="utf-8"))
            _mesclar(cfg, meu)
        except Exception as e:
            print(f"⚠️  Não consegui ler o config.json ({e}). Usando só os padrões.")
    # perfil de risco (moderado / agressivo / muito_agressivo); o que você escrever direto no config.json vale por cima
    fut = cfg.get("futuros", {})
    # taxas da corretora que você usa (a simulação fica igual à sua conta); o que estiver no seu config.json vale por cima
    corretora = ((cfg.get("conta_binance") or {}).get("corretora") or "bitget").lower()
    tab = TAXAS_CORRETORA.get(corretora)
    explicito_fut = meu.get("futuros", {}) if isinstance(meu.get("futuros"), dict) else {}
    if tab:
        for k, v in tab.items():
            if k not in explicito_fut:
                fut[k] = v
    if fut.get("pagar_taxas_com_bnb"):   # Binance dá 10% de desconto na taxa de futuros pagando com BNB
        fut["taxa_taker"] = round(fut.get("taxa_taker", 0.0005) * 0.9, 7)
        fut["taxa_maker"] = round(fut.get("taxa_maker", 0.0002) * 0.9, 7)
    perfil = (fut.get("perfis") or {}).get(fut.get("perfil"))
    if perfil:
        explicito = meu.get("futuros", {}) if isinstance(meu.get("futuros"), dict) else {}
        for k, v in perfil.items():
            if k not in explicito:
                fut[k] = v
    return cfg


def preparar_dados():
    """Na primeira vez, copia o histórico de preços e o boletim que vêm junto (dados_iniciais → dados)."""
    origem = AQUI / "dados_iniciais"
    if not origem.exists():
        return
    (DADOS / "historico").mkdir(parents=True, exist_ok=True)
    for f in (origem / "historico").glob("*.json.gz"):
        destino = DADOS / "historico" / f.name
        if not destino.exists():
            shutil.copy2(f, destino)
    if not (DADOS / "escola.json").exists() and (origem / "escola.json").exists():
        shutil.copy2(origem / "escola.json", DADOS / "escola.json")


def salvar(ag, arquivo=ARQ_SIM):
    DADOS.mkdir(exist_ok=True)
    ag.salvo_em = int(time.time() * 1000)
    tmp = arquivo.with_suffix(".tmp")
    tmp.write_text(json.dumps(ag.para_dict(), ensure_ascii=False), encoding="utf-8")
    for _ in range(10):
        try:
            os.replace(tmp, arquivo)
            return
        except PermissionError:  # Windows: o painel pode estar lendo o arquivo nesse instante
            time.sleep(0.1)


def imprimir_evento(e):
    print(f"  [{hhmm(e['t'])}] {e['emoji']} {e['texto']}")


# ---------------------------------------------------------------------------
def imprimir_boletim(esc, cfg):
    refs = esc["referencias"]
    r0, r1 = esc["periodo_oos"]
    ano = lambda t: time.strftime("%m/%Y", time.localtime(t / 1000))
    print()
    print("=" * 96)
    print(f" 🎓 BOLETIM DA ESCOLA DE TRADERS — provas fora da amostra de {ano(r0)} a {ano(r1)}, {esc['resultados'][0]['par']}")
    print("=" * 96)
    print(f" {'#':>2}  {'aluno':<30} {'nota':>4}  {'retorno':>8} {'queda máx':>9} {'Sharpe':>6} {'ops':>5} {'consist.':>8} {'custo x2':>8} {'confiança':>9}")
    print("-" * 96)
    times = [r["id"] for r in escolher_times(cfg, esc)]
    for k, r in enumerate(esc["resultados"], 1):
        o = r["oos"]
        selo = "✅" if r["aprovada"] else ("⚽" if r["id"] in times else "  ")
        print(f" {k:>2}{selo}{r['emoji']} {r['nome'][:27]:<27} {r['nota']:>4}  {o['retorno_pct']:>7.1f}% {o['max_dd_pct']:>8.1f}% "
              f"{o['sharpe']:>6.2f} {o['trades']:>5} {o['consistencia_pct']:>7.0f}% {o['retorno_custo_dobrado_pct']:>7.1f}% {o.get('dsr', 0) * 100:>8.0f}%")
    print("-" * 96)
    s, d = refs["segurar"], refs["dca"]
    print(f" 📌 Comprar e segurar a carteira: {s['retorno_pct']:+.1f}% (queda máx {s['max_dd_pct']:.0f}%, Sharpe {s['sharpe']})"
          f"   |   DCA semanal: {d['retorno_pct']:+.1f}% (queda máx {d['max_dd_pct']:.0f}%)")
    aprovadas = [r for r in esc["resultados"] if r["aprovada"]]
    print(f" 🏅 Aprovados em todos os critérios: {len(aprovadas)} de {len(esc['resultados'])}"
          + ("" if aprovadas else " — nenhum ainda; os times são formados pelas maiores notas"))
    com = esc.get("comite")
    if com:
        o = com["oos"]
        print(f" 🤝 Comitê ({' + '.join(com['nomes'])}): {o['retorno_pct']:+.1f}% · queda máx {o['max_dd_pct']:.1f}% · Sharpe {o['sharpe']}")
    if esc.get("mercado") == "futuros":
        print(" 💹 Prova em FUTUROS: LONG e SHORT, risco fixo por operação, alavancagem por julgamento, funding e liquidação.")
    print(" ⚽ Times da próxima temporada: " + ", ".join(f"{r.get('emoji') or ''} {r.get('nome_time') or r.get('nome')}" for r in escolher_times(cfg, esc)))
    print(f" ({esc['alunos_testados']} alunos, {esc['combinacoes_testadas']} combinações, {esc['duracao_s']}s)")
    print(" ⚠️  Resultado passado não garante o futuro. Simulação — não é recomendação de investimento.")
    print("=" * 96)


def cmd_escola(args):
    cfg = carregar_config()
    esc = escola_mod.rodar_escola(cfg.get("escola"), futuros=cfg.get("futuros"))
    imprimir_boletim(esc, cfg)
    if cfg.get("futuros", {}).get("ativo"):
        try:
            import escola_agencia
            print()
            escola_agencia.rodar(cfg, esc)
        except Exception as erro:
            print(f"⚠️  A prova da agência falhou: {erro}")
    print("\nVeja os detalhes no painel (aba 🎓 Escola). Pra montar os times com esse boletim: botão 'Nova temporada'.")


# ---------------------------------------------------------------------------
def escolher_times(cfg, esc):
    """Os N melhores alunos da escola viram os times (aprovados primeiro, depois por nota).
    Com `liga.times_fixos`, os times são exatamente os da lista (ex.: 3 times Seykota com ritmos diferentes)."""
    fixos = cfg["liga"].get("times_fixos")
    if fixos:
        por_id = {r["id"]: r for r in esc.get("resultados", [])}
        itv = cfg.get("modo", {}).get("intervalo_forcado")
        lista = []
        for f in fixos:
            base = por_id.get(f["estrategia"], {})
            params = dict(f["params"], **({"intervalo": itv} if itv else {}))
            lista.append({"id": f["id"], "estrategia": f["estrategia"], "nome_time": f.get("nome"), "emoji": f.get("emoji"),
                          "inspiracao": base.get("inspiracao", ""), "params_atuais": params, "params_fixos": True,
                          "nota": base.get("nota"), "oos": base.get("oos")})
        return lista
    fora = set(cfg["liga"].get("estrategias_excluidas", []))
    lista = [r for r in esc["resultados"] if r["id"] not in fora]
    if cfg["liga"].get("so_alunos_aprovados"):
        lista = [r for r in lista if r["aprovada"]] or lista[:1]
    n = cfg["liga"]["times"]
    com = cfg["liga"].get("comite", {})
    if com.get("ativo") and len(lista) >= com.get("membros", 3) and n >= 2:
        membros = lista[:com.get("membros", 3)]
        info = esc.get("comite") or {}
        comite = {"id": "comite", "nome": "Time Comitê", "emoji": "🤝", "comite": membros, "nota": info.get("nota"), "oos": info.get("oos")}
        return lista[:n - 1] + [comite]   # os N−1 melhores + o Comitê das 3 melhores
    return lista[:n]


SO_SAIDA = {"max_barras"}   # parâmetros que só mudam a saída (não mexem nas médias/sinais de entrada)


def aplicar_times_fixos(ag, cfg, avisar=print):
    """Times fixos do config valem já, sem recomeçar a temporada: nome/emoji novos e o RITMO de cada time.
    (Temporadas criadas por versões antigas não tinham a trava de ritmo fixo e o reestudo da escola deixava os 3 Seykota
    iguais — aqui o ritmo de cada um volta. Quem está com posição aberta troca quando fechar.)"""
    itv = cfg.get("modo", {}).get("intervalo_forcado")
    for f in cfg["liga"].get("times_fixos") or []:
        for tm in ag.times:
            if tm["id"] != f["id"]:
                continue
            tm["nome"], tm["emoji"] = f.get("nome") or tm["nome"], f.get("emoji") or tm["emoji"]
            fixo = dict(f["params"], intervalo=itv or tm.get("intervalo") or f["params"].get("intervalo", "4h"))
            corrigiu = not tm.get("params_fixos") or tm.get("params") != fixo
            tm["params_fixos"], tm["params"], tm["intervalo"] = True, dict(fixo), fixo["intervalo"]
            for tr in ag.do_time(tm["id"]):
                if tr.estrategia != f["estrategia"]:
                    continue
                difere = {k for k in set(tr.params) | set(fixo) if tr.params.get(k) != fixo.get(k)}
                if difere and difere <= SO_SAIDA:     # só muda a regra de SAÍDA: vale já, até pra quem está posicionado
                    tr.params, tr.params_novos = dict(fixo), None
                elif tr.params == fixo:
                    tr.params_novos = None            # cancela troca pendente vinda de um reestudo antigo
                else:
                    tr.params_novos = dict(fixo)
                    if not tr.posicao:
                        tr.aplicar_params_novos()
            if corrigiu:
                avisar(f"🔧 {tm['emoji']} {tm['nome']}: ritmo fixo garantido ({', '.join(f'{k} {v}' for k, v in f['params'].items())}).")


def adicionar_moedas_novas(ag, cfg, avisar=print):
    """Moedas que entraram no config com a temporada já rodando (liga.moedas + liga.moedas_novas): cada time ganha
    um trader pra cada moeda nova, com o dinheiro novo dividido igualmente, COMO SE existissem desde `desde`
    (horário de Brasília): entram no estado que a estratégia teria naquela hora e recuperam as velas desde então."""
    import calendar
    nv = cfg["liga"].get("moedas_novas") or {}
    por_time = cfg["liga"].get("traders_por_time") or len(cfg["liga"]["moedas"])
    moedas = cfg["liga"]["moedas"][:por_time]
    faltam = [(tm, par) for tm in ag.disputando() for par in moedas
              if not tm.get("membros") and not any(tr.time == tm["id"] and tr.par == par for tr in ag.traders)]
    if not faltam or not nv.get("capital_usd"):
        return
    t0 = int(time.time() * 1000)
    if nv.get("desde"):
        t0 = min(t0, (calendar.timegm(time.strptime(nv["desde"], "%Y-%m-%d %H:%M")) + 3 * 3600) * 1000)   # Brasília → UTC
    t0 = max(t0, ag.temporada.get("inicio", t0))
    cap = nv["capital_usd"] / len(faltam)
    itv = cfg.get("modo", {}).get("intervalo_forcado")
    novos = {}
    for tm, par in faltam:
        tr = Trader(ag.novo_nome() if cfg["liga"].get("nomes_traders") else moeda(par), cfg["liga"].get("emoji_trader", "🤖"),
                    par, 0.0, "trader", t0, tm["id"], tm["estrategia"], dict(tm["params"]))
        tr.capital_inicial = cap
        if itv:
            tr.intervalo_fixo = itv
        tr.alavancagem = tm.get("alavancagem", 1)
        ag.traders.append(tr)
        ag.aporte(tr, cap)
        novos.setdefault(tr.chave, []).append(tr)
    for chave, trs in novos.items():
        par, it = chave.split("@")
        passo = mercado.INTERVALOS_MS[it]
        for v in mercado.velas_desde(par, it, t0 - 1400 * passo):
            if v["t"] + passo <= t0:          # só o que já tinha fechado na hora em que eles "chegaram"
                ag.aquecer(chave, v)
        if ag._buf.get(chave, {}).get("c"):
            ag.ultimo_preco[par] = ag._buf[chave]["c"][-1]
            for tr in trs:
                tr.ultimo_preco = ag.ultimo_preco[par]
    for chave in novos:      # só depois de TODAS as moedas novas terem histórico (a alavancagem olha a carteira inteira)
        ag.sincronizar(chave, t0)
    ag.evento(t0, None, "🆕", f"Chegaram {len(faltam)} traders novos pras moedas {', '.join(sorted({moeda(p) for _, p in faltam}))} "
                              f"(US$ {nv['capital_usd']:,.0f} a mais na agência, US$ {cap:,.2f} pra cada), com as mesmas regras dos times")
    avisar(f"🆕 {len(faltam)} traders novos ({', '.join(sorted({moeda(p) for _, p in faltam}))}) desde {hhmm(t0)}: "
           f"US$ {cap:,.2f} cada. As velas desde então vão ser recuperadas agora.")


def custo_ida_e_volta(cfg):
    fut, md = cfg.get("futuros", {}), cfg.get("modo", {})
    entrada = fut.get("taxa_maker", 0.0002) if md.get("entrada_limitada", True) else fut.get("taxa_taker", 0.0005) + fut.get("derrapagem", 0.0002)
    return entrada + fut.get("taxa_taker", 0.0005) + fut.get("derrapagem", 0.0002)


def treinar_modelo(cfg, ag):
    """Modo 5 min: treina o modelo de chance de WIN com o histórico de 5 min (e mede nos últimos 30 dias)."""
    import historico
    import modelo
    md = cfg.get("modo", {})
    pares = md.get("moedas_treino", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"])
    print("🎲 Treinando o modelo de chance de WIN com o histórico de 5 min (na 1ª vez baixa uns meses de velas)...")
    for par in pares:
        for itv in ("5m", "4h"):
            try:
                historico.atualizar(par, itv)
            except Exception as e:
                print(f"   (não consegui atualizar {par} {itv}: {e})")
    fut = cfg.get("futuros", {})
    custo = custo_ida_e_volta(cfg)
    m, stats = modelo.treinar_do_historico(pares, md.get("alvo_atr", 3.0), md.get("stop_atr", 3.0), custo,
                                           lambda p, i: historico.como_dicionario(historico.carregar(p, i)))
    if m:
        ag.modelo_pesos, ag.modelo_treino = m.para_dict(), stats
        ag._modelo_obj = None
        print(f"   Pronto. Nos últimos {stats['dias_teste']} dias (que ele não viu), o lado escolhido teria ganhado "
              f"{stats['acerto_modelo_pct']}% das vezes (escolhendo ao acaso: {stats['acerto_ao_acaso_pct']}%).")
        ag.evento(int(time.time() * 1000), None, "🎲", f"Modelo de chance treinado: acerto fora da amostra {stats['acerto_modelo_pct']}% "
                                                        f"(ao acaso {stats['acerto_ao_acaso_pct']}%). Agora ele aprende a cada vela.")


def preparar_velas(ag):
    """Aquece o histórico recente de cada par/intervalo e devolve as velas novas a processar."""
    novas = []
    agora = int(time.time() * 1000)
    for chave in ag.chaves():
        par, itv = chave.split("@")
        passo = mercado.INTERVALOS_MS[itv]
        ultimo = ag.ultimo_t.get(chave)
        desde = (ultimo or agora) - 1400 * passo if chave not in ag._buf else ultimo + passo
        for v in mercado.velas_desde(par, itv, desde):
            if ultimo is None or v["t"] <= ultimo:
                ag.aquecer(chave, v)
            else:
                novas.append((v["t"], chave, v))
    return sorted(novas, key=lambda x: (x[0], x[1]))


def resumo_liga(ag):
    print("\n⚽ LIGA — temporada", ag.temporada["numero"], "| próxima rodada:", hhmm(ag.temporada["proxima_rodada"]))
    for tm in sorted(ag.times, key=lambda x: x["lugar"] or 99):
        r = ag.resumo_time(tm)
        papel = "🏆 TITULAR" if tm["titular"] else ("⚡ fora   " if tm.get("especial") else "   reserva")
        alav = ("vol" if ag.vol_ativo() else f"{tm.get('alavancagem') or 1}x" if tm.get("especial") else f"≤{tm.get('alavancagem') or 1}x") if ag.futuros() else ""
        print(f"  {tm['lugar'] or '–'}º {papel}  {tm['emoji']} {tm['nome']:<18} {tm['intervalo']:>3} {alav} patrimônio US$ {r['patrimonio']:8.2f}"
              f"  ({r['resultado_pct']:+.2f}%)  traders {len(ag.do_time(tm['id']))}")
    print()


def cmd_simular(args):
    cfg = carregar_config()
    sincronia.baixar(cfg)   # outro PC salvou algo mais novo? continua de lá
    esc = escola_mod.carregar()
    if not esc:
        print("🎓 A escola ainda não rodou — rodando agora pra montar os times (na 1ª vez baixa o histórico: pode levar uns minutos)...")
        esc = escola_mod.rodar_escola(cfg.get("escola"), futuros=cfg.get("futuros"))
        imprimir_boletim(esc, cfg)
        try:
            import escola_agencia
            escola_agencia.rodar(cfg, esc)
        except Exception as erro:
            print(f"⚠️  A prova da agência falhou: {erro}")
    fut = cfg.get("futuros", {})
    esc_fut = (esc.get("config") or {}).get("futuros") or {}
    perfil_mudou = any(esc_fut.get(k) != fut.get(k) for k in ("risco_por_operacao", "piramide", "alavancagem_min", "alavancagem_max"))
    if fut.get("ativo") and (esc.get("mercado") != "futuros" or perfil_mudou):
        print("🎓 A escola vai refazer as provas em FUTUROS (LONG e SHORT, risco fixo, alavancagem por julgamento) — ~1 minuto...")
        esc = escola_mod.rodar_escola(cfg.get("escola"), futuros=fut)
        imprimir_boletim(esc, cfg)
    if fut.get("ativo"):
        if mercado.usar_futuros(fut.get("dados_reais", True)):
            print("💹 Usando os dados de FUTUROS de verdade da Binance (preço do contrato e funding real).")
        else:
            print("💹 A API de futuros da Binance não respondeu daqui — usando o preço à vista e funding médio (aproximação).")
    agora = int(time.time() * 1000)
    ag = None
    if ARQ_SIM.exists():
        d = json.loads(ARQ_SIM.read_text(encoding="utf-8"))
        if not d.get("times"):
            backup = DADOS / f"simulacao_versao_antiga_{time.strftime('%Y%m%d_%H%M')}.json"
            shutil.move(ARQ_SIM, backup)
            print(f"📦 A simulação da versão antiga foi guardada em dados/{backup.name}.")
        else:
            if d.get("versao", 1) in (8, 9, 10):
                # a mudança pra 9 traders / US$ 500 foi desfeita: volta pra temporada de 15 traders guardada antes dela
                copias = sorted(DADOS.glob("simulacao_antes_dos_9_*.json"))
                if not copias:
                    copias = [c for c in sorted(DADOS.glob("simulacao_antiga_*.json"))
                              if json.loads(c.read_text(encoding="utf-8")).get("versao") == 7]
                if copias:
                    shutil.copy2(ARQ_SIM, DADOS / f"simulacao_desfeita_{time.strftime('%Y%m%d_%H%M')}.json")
                    d = json.loads(copias[-1].read_text(encoding="utf-8"))
                    print(f"↩️  Voltei pra temporada de 15 traders guardada em dados/{copias[-1].name} (a de 9 ficou em dados/simulacao_desfeita_*.json).")
            ag = Agencia.de_dict(d, cfg)
            print(f"📂 Continuando a temporada {ag.temporada['numero']} (começou em {hhmm(ag.temporada['inicio'])})")
            if cfg.get("futuros", {}).get("ativo") and (not ag.futuros() or getattr(ag, "versao", 1) < 15):
                backup = DADOS / f"simulacao_antiga_{time.strftime('%Y%m%d_%H%M')}.json"
                shutil.copy2(ARQ_SIM, backup)
                tipo = cfg.get("modo", {}).get("tipo")
                novo = ("MODO 4H: 3 times Seykota (rápido, médio, lento) + Momentum AQR em BTC/ETH/SOL, alavancagem pela volatilidade e conta real dividida entre os 4"
                        if tipo == "4h_vol" else "MODO 5 MIN" if tipo == "5m"
                        else f"perfil {fut.get('perfil')}: risco de {fut.get('risco_por_operacao', 0) * 100:.0f}% por operação")
                print(f"🔁 Recomeçando a agência ({novo}). A temporada anterior foi guardada em dados/{backup.name}.")
                ag = None
    ag = ag or Agencia(cfg, agora)
    ag.ao_evento = imprimir_evento
    import modelo as _modelo
    if ag.modo5m() and (not getattr(ag, "modelo_pesos", None)
                        or len((ag.modelo_pesos or {}).get("long", [])) != len(_modelo.NOMES) + 1):
        treinar_modelo(cfg, ag)   # sem modelo, ou modelo de uma versão com menos sinais (ex.: antes do BTC)
    if not ag.times:
        ag.nova_temporada(escolher_times(cfg, esc), agora)
    aplicar_times_fixos(ag, cfg)
    adicionar_moedas_novas(ag, cfg)
    fora = set(cfg["liga"].get("estrategias_excluidas", []))
    for tm in list(ag.disputando()):
        if tm.get("estrategia") in fora:
            ag.remover_time(tm["id"], agora, "foi encerrado pelo CEO")
    ag.adicionar_mesa_rapida(agora)
    if not ag.sprint:
        ag.abrir_sprint(agora)
    ag.escola_aplicada = getattr(ag, "escola_aplicada", None) or esc.get("gerado_em")

    fila = queue.Queue()
    painel.iniciar(ARQ_SIM, fila=fila, abrir_navegador=not args.sem_navegador,
                   celular=cfg.get("painel", {}).get("celular", True), senha=cfg.get("painel", {}).get("senha"),
                   porta=cfg.get("painel", {}).get("porta", 8000))
    resumo_liga(ag)
    print("Ctrl+C pra parar (tudo fica salvo). Deixe esta janela aberta.\n")

    try:
        _laco(args, cfg, esc, ag, fila, operacao_real.Operacao(cfg))
    except KeyboardInterrupt:
        if sincronia.ativo(cfg):
            print("\n☁️  Guardando na nuvem antes de fechar...")
            salvar(ag)
            sincronia.enviar(cfg, final=True)
        raise


def _laco(args, cfg, esc, ag, fila, op=None):
    proxima_busca = 0
    ultima_cotacao = 0
    ultimo_reestudo = 0
    gerente_ocupado = threading.Event()
    gerente_erro_ate = [0]
    while True:
        try:
            agora = int(time.time() * 1000)
            # 1) Pedidos do painel
            while not fila.empty():
                cmd = fila.get()
                if cmd.get("acao") == "nova_temporada":
                    esc = escola_mod.carregar() or esc
                    ag.nova_temporada(escolher_times(cfg, esc), agora)
                    ag.escola_aplicada = esc.get("gerado_em")
                    resumo_liga(ag)
                elif cmd.get("acao") == "rodada_agora":
                    ag.rodada(agora)
                    ag.fechar_sprint(agora)
                    resumo_liga(ag)
                elif cmd.get("acao") == "parar_real" and op:
                    op.parar_tudo("botão PARAR TUDO no painel")
                elif cmd.get("acao") == "retomar_real" and op:
                    op.retomar()
                elif cmd.get("acao") == "igualar_real":
                    alvo_usd = cmd.get("valor") or (op.estado.get("patrimonio") if op and op.ativo else None)
                    if alvo_usd and float(alvo_usd) >= 10 and ag.patrimonio() > 0:
                        f = float(alvo_usd) / ag.patrimonio()
                        ag.reescalar(f, int(time.time() * 1000), "valor digitado" if cmd.get("valor") else "saldo da corretora")
                        salvar(ag)
                    else:
                        print("⚖️  Não ajustei: preciso de um saldo de pelo menos US$ 10 (da corretora ou digitado).")
            # 2) Saiu boletim novo da escola?
            novo = escola_mod.carregar()
            if novo and novo.get("gerado_em") != ag.escola_aplicada:
                esc, ag.escola_aplicada = novo, novo.get("gerado_em")
                if novo.get("mercado", "spot") == ag.mercado:
                    ag.reestudar(novo, agora)
                top = [r["id"] for r in escolher_times(cfg, esc)]
                if sorted(top) != sorted(tm["id"] for tm in ag.times):
                    ag.evento(agora, None, "📜", "Novo boletim da escola: o top 5 mudou (veja na aba Escola)")
                try:   # a prova da agência diz se algum aluno novo merece entrar no escritório
                    import escola_agencia
                    pa = escola_agencia.carregar()
                    if pa:
                        cand = [a for a in pa["alunos"] if a["veredito"].startswith(("👑", "🤝"))]
                        ag.evento(agora, None, "🎓", (f"Escola: {', '.join(a['emoji'] + ' ' + a['nome'] + ' (' + a['veredito'] + ')' for a in cand)} "
                                                       "— veja a prova da agência na aba Escola") if cand else
                                  f"Escola: {len(pa['alunos'])} alunos testados como se operassem no escritório — nenhum supera o campeão "
                                  f"({pa['campeao']['nome']}, {pa['campeao']['ao_ano_pct']:+.0f}% ao ano)")
                except Exception:
                    pass
            # 2b) Reestudo: a escola refaz as provas com os dados novos a cada N dias (em segundo plano)
            dias_re = cfg.get("aprendizado", {}).get("reestudar_a_cada_dias", 7)
            if dias_re and esc and agora - esc.get("gerado_em", agora) > dias_re * 86_400_000 \
                    and time.time() - ultimo_reestudo > 6 * 3600 and not painel.escola_rodando():
                ultimo_reestudo = time.time()
                painel.rodar_escola_em_segundo_plano()
                ag.evento(agora, None, "🎓", "A escola começou a reestudar com os dados mais novos (os times atualizam quando terminar)")
            # 3) Rodada da semana e fim da sprint (de 1 dia, por padrão) — só depois de recuperar as velas perdidas
            if proxima_busca and agora >= ag.temporada["proxima_rodada"]:
                ag.rodada(agora)
                resumo_liga(ag)
            if proxima_busca and ag.sprint and agora >= ag.sprint["fim"]:
                retro = ag.fechar_sprint(agora)
                if retro and gerente.status()[0]:
                    threading.Thread(target=lambda r=retro: _retro(r), daemon=True).start()
            # 4) Preços e velas
            if time.time() >= proxima_busca:
                if time.time() - ultima_cotacao > 600:
                    ag.cotacao_brl = mercado.cotacao_brl() or ag.cotacao_brl
                    if ag.futuros():
                        ag.funding_real = mercado.funding(ag.pares()) or None
                        ag.fonte_dados = mercado.fonte()
                    ultima_cotacao = time.time()
                novas = preparar_velas(ag)
                for chave in ag.chaves():
                    ag.sincronizar(chave, agora)
                if len(novas) > 40:
                    print(f"⏩ Recuperando {len(novas)} velas que fecharam enquanto o programa estava desligado...")
                for t, chave, v in novas:
                    # vela por vela, na ordem do tempo: rodadas e sprints (dias) fecham na hora certa, mesmo na recuperação
                    tf = t + mercado.INTERVALOS_MS[chave.split("@")[1]]
                    if tf < agora:
                        if tf >= ag.temporada["proxima_rodada"]:
                            ag.rodada(tf)
                        if ag.sprint and tf >= ag.sprint["fim"]:
                            ag.fechar_sprint(tf)
                    ag.processar_vela(chave, v)
                    if tf < agora:
                        ag.marcar_curva(tf)
                ag.atualizar_precos(mercado.precos(ag.pares()))
                ag.marcar_curva(agora)
                salvar(ag)
                sincronia.talvez_enviar(cfg)
                if op and op.ativo:   # a conta da Binance segue a agência (só no PC marcado pra operar)
                    op.ciclo(ag, dict(ag.ultimo_preco))
                proxima_busca = time.time() + args.segundos
            # 5) Relatório diário do gerente
            g_cfg = cfg.get("gerente", {})
            if g_cfg.get("relatorio_automatico", True) and not gerente_ocupado.is_set() and time.time() > gerente_erro_ate[0]:
                ok, _ = gerente.status()
                rel = gerente.carregar().get("relatorio")
                if ok and (not rel or agora - rel["t"] > g_cfg.get("horas_entre_relatorios", 24) * 3_600_000):
                    gerente_ocupado.set()

                    def _relatorio():
                        try:
                            gerente.gerar_relatorio(json.loads(ARQ_SIM.read_text(encoding="utf-8")), escola_mod.carregar())
                            print("  🧠 O gerente escreveu o relatório do dia (aba Gerente)")
                        except Exception as e:
                            gerente.registrar_erro(str(e))
                            gerente_erro_ate[0] = time.time() + 3600
                            print(f"  🧠 O gerente não conseguiu escrever o relatório: {e}")
                        finally:
                            gerente_ocupado.clear()
                    threading.Thread(target=_relatorio, daemon=True).start()
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"⚠️  Algo falhou ({e}). Tento de novo já já.")
            proxima_busca = time.time() + args.segundos
        time.sleep(1)


def _retro(sprint):
    try:
        gerente.gerar_retro(sprint, escola_mod.carregar())
        print(f"  🧠 O gerente escreveu a retrospectiva da sprint {sprint['numero']} (aba Sprints)")
    except Exception as e:
        print(f"  🧠 O gerente não conseguiu escrever a retrospectiva: {e}")


def cmd_sincronia(args):
    """Liga a sincronia entre PCs (a mesma simulação no trabalho e em casa)."""
    pessoal = AQUI / "config.json"
    meu = {}
    if pessoal.exists():
        try:
            meu = json.loads(pessoal.read_text(encoding="utf-8"))
        except Exception:
            print("⚠️  Não consegui ler o config.json — conserte ou apague ele e rode de novo.")
            return

    def salvar_config(c):
        pessoal.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")
    if not (meu.get("sincronizar") or {}).get("repo"):
        # o repositório de dados é SEU (privado): pergunta o usuário do GitHub (quem baixou de outra pessoa usa o próprio)
        padrao = (sincronia.repo_padrao() or "").rstrip("/").replace(".git", "").split("/")[-2:-1]
        dono = input(f"Seu usuário do GitHub{f' (Enter = {padrao[0]})' if padrao else ''}: ").strip() or (padrao[0] if padrao else "")
        if not dono:
            print("Preciso do seu usuário do GitHub pra achar o repositório escritoriotrade-dados."); return
        meu.setdefault("sincronizar", {})["repo"] = f"https://github.com/{dono}/escritoriotrade-dados.git"
    sincronia.ligar(salvar_config, meu, usar_este=getattr(args, "usar_este", False))


def cmd_binance(args):
    """Conecta a conta de futuros (Binance ou Bybit) — chave digitada AQUI, nunca no chat — e escolhe o modo."""
    import getpass
    import binance_real
    pessoal = AQUI / "config.json"
    meu = json.loads(pessoal.read_text(encoding="utf-8")) if pessoal.exists() else {}
    print("\n💵 CONTA DE FUTUROS — a conta da corretora vai copiar a agência (na proporção).\n")
    print("  Qual corretora?")
    print("  1) Binance")
    print("  2) Bybit")
    print("  3) Bitget")
    corretora = {"1": "binance", "2": "bybit", "3": "bitget"}.get(input("\nEscolha (1-3): ").strip())
    if not corretora:
        print("Opção inválida."); return
    nome = binance_real.NOMES[corretora]
    treino = ("Demo Trading da Bybit (no site da Bybit, ligue o modo Demo e crie a chave lá)" if corretora == "bybit"
              else "não disponível na Bitget — use o papel pra treinar" if corretora == "bitget"
              else "Binance de TREINO (crie a chave em testnet.binancefuture.com)")
    print(f"\n  Modo na {nome}:")
    print("  1) papel    — só anota as ordens que mandaria (sem chave, sem risco)")
    print(f"  2) treino   — {treino}, dinheiro de mentira")
    print("  3) real     — DINHEIRO DE VERDADE")
    print("  4) desligar")
    op = input("\nEscolha (1-4): ").strip()
    modo = {"1": "papel", "2": "testnet", "3": "real", "4": "desligado"}.get(op)
    if not modo:
        print("Opção inválida."); return
    if corretora == "bitget" and modo == "testnet":
        print("A Bitget não tem conta de treino pela API aqui: escolha o papel (1) pra treinar, ou o real (3)."); return
    if modo in ("testnet", "real"):
        if modo == "real":
            print(f"\n⚠️  ANTES DE SEGUIR, confira na {nome} (Gerenciamento de API):")
            if corretora == "bybit":
                print("   • a chave tem SÓ 'Contrato → Ordens' e 'Contrato → Posições' — NUNCA saque nem transferência;")
            elif corretora == "bitget":
                print("   • a chave tem SÓ 'Futuros → Ordens/Posições' (leitura e escrita) — NUNCA saque nem transferência;")
            else:
                print("   • a chave tem SÓ 'Ativar Futuros' (e leitura) — NUNCA 'Ativar Saques';")
            print("   • restrita ao IP deste PC (mais seguro);")
            print("   • na conta de derivativos/futuros tem só o valor que você aceita perder.")
            print("   Recomendado: rodar antes uns dias no modo treino.")
            if input("\nDigite EU ENTENDO O RISCO pra continuar: ").strip().upper() != "EU ENTENDO O RISCO":
                print("Cancelado."); return
        chave = input("API Key: ").strip()
        segredo = getpass.getpass("Secret Key (não aparece enquanto digita): ").strip()
        frase = getpass.getpass("Passphrase da chave (a senha que você criou junto com a chave; não aparece): ").strip() if corretora == "bitget" else None
        cli = binance_real.criar_cliente(corretora, modo, chave, segredo, frase)
        try:
            cli.sincronizar_relogio()
            c = cli.conta()
        except Exception as e:
            print(f"\n❌ Não consegui entrar na conta: {e}\n   Confira a chave, as permissões de derivativos/futuros e a restrição de IP.")
            return
        binance_real.salvar_chave(modo, chave, segredo, corretora, frase)
        print(f"\n✅ Conectado na {nome} ({'treino' if modo == 'testnet' else modo}). Patrimônio: US$ {c['patrimonio']:,.2f} · "
              f"posições abertas: {c['posicoes'] or 'nenhuma'}")
        if c["patrimonio"] < 50:
            print(f"   🟡 A conta está sem saldo — tudo bem pra testar: a agência fica conectada sem mandar ordens. Quando você "
                  f"depositar USDT nos Futuros USDT-M da {nome}, ela começa a copiar sozinha.")
        if c["posicoes"]:
            print("   ⚠️  Já existem posições abertas nessa conta. A agência vai AJUSTAR essas moedas pro que ela quer ter.")
    meu.setdefault("conta_binance", {}).update({"modo": modo, "corretora": corretora, "operar_neste_pc": modo != "desligado"})
    pessoal.write_text(json.dumps(meu, ensure_ascii=False, indent=2), encoding="utf-8")
    if modo != "desligado":
        print(f"\nPronto: ESTE PC vai operar a conta da {nome} em modo {modo.upper()} quando a agência estiver ligada.")
        print("Travas: perde mais de 15% num dia ou cai abaixo de 50% do que começou → fecha tudo e PARA.")
        print(f"Stop de emergência na própria {nome} a 20% (protege com o PC desligado).")
        print("Pra parar na hora: botão PARAR TUDO no escritório, ou crie o arquivo dados/PARAR_REAL.")
    else:
        print("Operação real desligada neste PC.")


def cmd_reconstruir(args):
    """Refaz uma temporada desde uma data (ex.: a do PC do trabalho): mesmas velas → mesmas decisões dos traders."""
    import calendar
    cfg = carregar_config()
    esc = escola_mod.carregar()
    if not esc:
        print("A escola ainda não rodou neste PC. Ligue a agência uma vez antes (2_ligar_agencia.bat)."); return
    try:   # data/hora de Brasília → UTC
        t0 = (calendar.timegm(time.strptime(args.inicio, "%Y-%m-%d %H:%M")) + 3 * 3600) * 1000
    except ValueError:
        print('Data inválida. Use assim: "2026-11-10 12:00"'); return
    agora = int(time.time() * 1000)
    print(f"🔁 Refazendo a temporada desde {args.inicio} (Brasília): os traders vão tomar as mesmas decisões, vela por vela...")
    if cfg.get("futuros", {}).get("ativo"):
        mercado.usar_futuros(cfg["futuros"].get("dados_reais", True))
    ag = Agencia(cfg, t0)
    if ag.modo5m():
        treinar_modelo(cfg, ag)
    ag.nova_temporada(escolher_times(cfg, esc), t0)
    ag.ao_evento = imprimir_evento
    novas = []
    for chave in ag.chaves():
        par, itv = chave.split("@")
        passo = mercado.INTERVALOS_MS[itv]
        for v in mercado.velas_desde(par, itv, t0 - 1400 * passo):
            if v["t"] + passo <= t0:
                ag.aquecer(chave, v)
            elif v["t"] + passo <= agora:
                novas.append((v["t"] + passo, chave, v))
    for chave in ag.chaves():
        ag.sincronizar(chave, t0)
    for tf, chave, v in sorted(novas, key=lambda x: (x[0], x[1])):
        if tf >= ag.temporada["proxima_rodada"]:
            ag.rodada(tf)
        if ag.sprint and tf >= ag.sprint["fim"]:
            ag.fechar_sprint(tf)
        ag.processar_vela(chave, v)
        ag.marcar_curva(tf)
    ag.atualizar_precos(mercado.precos(ag.pares()))
    ag.marcar_curva(agora)
    ag.escola_aplicada = esc.get("gerado_em")
    if ARQ_SIM.exists():
        copia = DADOS / f"simulacao_antes_de_refazer_{time.strftime('%Y%m%d_%H%M')}.json"
        shutil.copy2(ARQ_SIM, copia)
        print(f"   (a simulação que estava aqui ficou guardada em dados/{copia.name})")
    salvar(ag)
    resumo_liga(ag)
    if sincronia.ativo(cfg):
        sincronia._preparar_pasta(sincronia._cfg(cfg)["repo"], print)
        sincronia.enviar(cfg, final=True, forcar=True)
    print("✅ Pronto! Agora ligue a agência (2_ligar_agencia.bat): ela continua desta temporada.")


def cmd_resumo(args):
    """Resumo em texto (pra conferir ou mandar pro Claude). Não mostra chave nem nada pessoal."""
    if not ARQ_SIM.exists():
        print("Ainda não tem simulação. Abra o 2_ligar_agencia.bat primeiro.")
        return
    d = json.loads(ARQ_SIM.read_text(encoding="utf-8"))
    agora = int(time.time() * 1000)
    L = []
    salvo = d.get("salvo_em") or 0
    L.append(f"RESUMO DA AGÊNCIA — {time.strftime('%d/%m/%Y %H:%M')}")
    L.append(f"Última atualização da simulação: {hhmm(salvo)} ({(agora - salvo) / 60000:.0f} min atrás)"
             + ("  ⚠️ a agência parece DESLIGADA" if agora - salvo > 5 * 60000 else "  ✅ ligada"))
    temp = d.get("temporada") or {}
    L.append(f"Temporada {temp.get('numero')} desde {hhmm(temp.get('inicio', 0))} · próxima rodada {hhmm(temp.get('proxima_rodada', 0))}")
    L.append("")
    for tm in sorted(d.get("times", []), key=lambda x: x.get("lugar") or 99):
        trs = [t for t in d["traders"] if t["time"] == tm["id"]]
        ops24 = sum(1 for t in trs for o in t.get("trades", []) if agora - o["t_saida"] < 86_400_000)
        abertos = sum(1 for t in trs if t.get("posicao"))
        longs = sum(1 for t in trs if (t.get("posicao") or {}).get("lado") == 1)
        shorts = sum(1 for t in trs if (t.get("posicao") or {}).get("lado") == -1)
        liqs = sum(t.get("liquidacoes", 0) for t in trs)
        L.append(f"{tm['emoji']} {tm['nome']} ({tm['intervalo']}) {'TITULAR' if tm.get('titular') else ''}: patrimônio US$ {tm['patrimonio']:.2f} "
                 f"({tm['resultado_pct']:+.2f}%) · operações nas últimas 24h: {ops24} · "
                 + (f"LONG {longs} / SHORT {shorts} de {len(trs)} · liquidações {liqs} · caixa do time US$ {tm.get('caixa_time', 0):.0f}" if d.get("mercado") == "futuros"
                    else f"comprados agora: {abertos}/{len(trs)}"))
        if tm.get("modo") == "grade":
            for t in trs:
                g = t.get("grade_estado") or {}
                c = g.get("centro")
                var = (t["ultimo_preco"] / c - 1) * 100 if c and t.get("ultimo_preco") else None
                L.append(f"    {t['nome']}: lotes comprados {len(g.get('lotes', {}))} · vendas {t['vitorias'] + t['derrotas']} · "
                         f"preço vs centro da grade {'%+.2f%%' % var if var is not None else '(grade ainda não começou)'} · {t.get('gatilho') or ''}")
    sp = d.get("sprint_atual")
    if sp:
        tt = sp["total"]
        L.append("")
        L.append(f"Sprint {sp['numero']} (dia {sp['dias']}): {tt['operacoes']} operações dos times · resultado {tt['lucro_pct']:+.2f}% · taxas US$ {tt['taxas']:.2f}")
        for x in sp["times"]:
            if x["especial"]:
                L.append(f"  {x['emoji']} {x['nome']}: {x['operacoes']} operações · resultado {x['lucro_pct']:+.2f}% · taxas US$ {x['taxas']:.2f}")
    L.append("")
    L.append("Últimos 10 eventos:")
    for e in d.get("eventos", [])[-10:]:
        L.append(f"  [{hhmm(e['t'])}] {e['emoji']} {e['texto']}")
    texto = "\n".join(L)
    print(texto)
    (DADOS / "resumo_para_o_claude.txt").write_text(texto, encoding="utf-8")
    print(f"\n(Salvo em {DADOS / 'resumo_para_o_claude.txt'} — pode mandar esse arquivo ou colar o texto pro Claude.)")


def cmd_painel(args):
    pc = carregar_config().get("painel", {})
    painel.iniciar(ARQ_SIM, bloquear=True, celular=pc.get("celular", True), senha=pc.get("senha"), porta=pc.get("porta", 8000))


def cmd_zerar(args):
    if not ARQ_SIM.exists():
        print("Não tem simulação salva.")
        return
    if input("Apagar a simulação e começar do zero? (s/n) ").strip().lower() == "s":
        ARQ_SIM.unlink()
        print("Pronto, apagada.")


def menu():
    print("\n🏢  AGÊNCIA DE TRADE (simulada)\n")
    print("  1  🎓 Rodar a Escola de Traders (testa as estratégias e escolhe os 5 times)")
    print("  2  ⚽ Ligar a liga ao vivo + escritório")
    print("  3  🖥️  Só abrir o escritório/painel")
    print("  4  🧹 Zerar a simulação")
    escolha = input("\nEscolha (1-4): ").strip()
    return {"1": "escola", "2": "simular", "3": "painel", "4": "zerar"}.get(escolha)


def main():
    ap = argparse.ArgumentParser(description="Agência de Trade (simulada)")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("escola", help="roda a Escola de Traders")
    sub.add_parser("backtest", help="(antigo) mesmo que escola")
    s = sub.add_parser("simular", help="liga a liga ao vivo com dinheiro de mentira")
    s.add_argument("--segundos", type=int, default=20, help="de quanto em quanto tempo olha o mercado")
    s.add_argument("--sem-navegador", action="store_true")
    sub.add_parser("painel", help="abre o escritório/painel")
    sub.add_parser("zerar", help="apaga a simulação")
    sub.add_parser("resumo", help="mostra um resumo em texto (pra mandar pro Claude)")
    sc = sub.add_parser("sincronia", help="liga a sincronia entre PCs (mesma simulação em casa e no trabalho)")
    sc.add_argument("--usar-este", action="store_true", help="a simulação deste PC passa a valer em todos")
    sub.add_parser("binance", help="conecta a conta de futuros da Binance (papel, testnet ou real)")
    rc = sub.add_parser("reconstruir", help="refaz a temporada desde uma data (ex.: a do outro PC)")
    rc.add_argument("--inicio", required=True, help='data e hora de Brasília, ex.: "2026-11-10 12:00"')
    args = ap.parse_args()
    preparar_dados()
    cmd = args.cmd or menu()
    if cmd == "simular" and not hasattr(args, "segundos"):
        args.segundos, args.sem_navegador = 20, False
    acoes = {"escola": cmd_escola, "backtest": cmd_escola, "simular": cmd_simular, "painel": cmd_painel, "zerar": cmd_zerar, "resumo": cmd_resumo, "sincronia": cmd_sincronia, "binance": cmd_binance, "reconstruir": cmd_reconstruir}
    if cmd not in acoes:
        print("Opção inválida.")
        return
    try:
        acoes[cmd](args)
    except KeyboardInterrupt:
        print("\n👋 Agência fechada. Tudo salvo — rode de novo pra continuar.")


if __name__ == "__main__":
    main()
