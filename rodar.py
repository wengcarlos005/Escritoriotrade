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
from motor import Agencia, hhmm, moeda

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


def carregar_config():
    """Padrões em config.padrao.json (vem nas atualizações) + o que você mudar em config.json (só seu)."""
    cfg = json.loads((AQUI / "config.padrao.json").read_text(encoding="utf-8"))
    pessoal = AQUI / "config.json"
    if pessoal.exists():
        try:
            _mesclar(cfg, json.loads(pessoal.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"⚠️  Não consegui ler o config.json ({e}). Usando só os padrões.")
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
    print(" ⚽ Times da próxima temporada: " + ", ".join(f"{r['emoji']} {r['nome']}" for r in escolher_times(cfg, esc)))
    print(f" ({esc['alunos_testados']} alunos, {esc['combinacoes_testadas']} combinações, {esc['duracao_s']}s)")
    print(" ⚠️  Resultado passado não garante o futuro. Simulação — não é recomendação de investimento.")
    print("=" * 96)


def cmd_escola(args):
    cfg = carregar_config()
    esc = escola_mod.rodar_escola(cfg.get("escola"))
    imprimir_boletim(esc, cfg)
    print("\nVeja os detalhes no painel (aba 🎓 Escola). Pra montar os times com esse boletim: botão 'Nova temporada'.")


# ---------------------------------------------------------------------------
def escolher_times(cfg, esc):
    """Os N melhores alunos da escola viram os times (aprovados primeiro, depois por nota)."""
    lista = list(esc["resultados"])
    if cfg["liga"].get("so_alunos_aprovados"):
        lista = [r for r in lista if r["aprovada"]] or lista[:1]
    return lista[:cfg["liga"]["times"]]


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
        print(f"  {tm['lugar'] or '–'}º {papel}  {tm['emoji']} {tm['nome']:<18} {tm['intervalo']:>3}  patrimônio US$ {r['patrimonio']:8.2f}"
              f"  ({r['resultado_pct']:+.2f}%)  traders {len(ag.do_time(tm['id']))}")
    print()


def cmd_simular(args):
    cfg = carregar_config()
    esc = escola_mod.carregar()
    if not esc:
        print("🎓 A escola ainda não rodou — rodando agora pra montar os times (leva ~1 minuto)...")
        esc = escola_mod.rodar_escola(cfg.get("escola"))
        imprimir_boletim(esc, cfg)
    agora = int(time.time() * 1000)
    ag = None
    if ARQ_SIM.exists():
        d = json.loads(ARQ_SIM.read_text(encoding="utf-8"))
        if not d.get("times"):
            backup = DADOS / f"simulacao_versao_antiga_{time.strftime('%Y%m%d_%H%M')}.json"
            shutil.move(ARQ_SIM, backup)
            print(f"📦 A simulação da versão antiga foi guardada em dados/{backup.name}.")
        else:
            ag = Agencia.de_dict(d, cfg)
            print(f"📂 Continuando a temporada {ag.temporada['numero']} (começou em {hhmm(ag.temporada['inicio'])})")
    ag = ag or Agencia(cfg, agora)
    ag.ao_evento = imprimir_evento
    if not ag.times:
        ag.nova_temporada(escolher_times(cfg, esc), agora)
    ag.adicionar_mesa_rapida(agora)
    if not ag.sprint:
        ag.abrir_sprint(agora)
    ag.escola_aplicada = getattr(ag, "escola_aplicada", None) or esc.get("gerado_em")

    fila = queue.Queue()
    painel.iniciar(ARQ_SIM, fila=fila, abrir_navegador=not args.sem_navegador)
    resumo_liga(ag)
    print("Ctrl+C pra parar (tudo fica salvo). Deixe esta janela aberta.\n")

    proxima_busca = 0
    ultima_cotacao = 0
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
                    resumo_liga(ag)
            # 2) Saiu boletim novo da escola?
            novo = escola_mod.carregar()
            if novo and novo.get("gerado_em") != ag.escola_aplicada:
                esc, ag.escola_aplicada = novo, novo.get("gerado_em")
                top = [r["id"] for r in escolher_times(cfg, esc)]
                if sorted(top) != sorted(tm["id"] for tm in ag.times):
                    ag.evento(agora, None, "📜", "Novo boletim da escola: o top 5 mudou (veja na aba Escola)")
            # 3) Rodada da semana
            if agora >= ag.temporada["proxima_rodada"]:
                ag.rodada(agora)
                resumo_liga(ag)
                retro = ag.sprints[-1] if ag.sprints else None
                if retro and gerente.status()[0]:
                    threading.Thread(target=lambda r=retro: _retro(r), daemon=True).start()
            # 4) Preços e velas
            if time.time() >= proxima_busca:
                if time.time() - ultima_cotacao > 600:
                    ag.cotacao_brl = mercado.cotacao_brl() or ag.cotacao_brl
                    ultima_cotacao = time.time()
                novas = preparar_velas(ag)
                for chave in ag.chaves():
                    ag.sincronizar(chave, agora)
                if len(novas) > 40:
                    print(f"⏩ Recuperando {len(novas)} velas que fecharam enquanto o programa estava desligado...")
                for t, chave, v in novas:
                    ag.processar_vela(chave, v)
                ag.atualizar_precos(mercado.precos(ag.pares()))
                ag.marcar_curva(agora)
                salvar(ag)
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


def cmd_painel(args):
    painel.iniciar(ARQ_SIM, bloquear=True)


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
    args = ap.parse_args()
    preparar_dados()
    cmd = args.cmd or menu()
    if cmd == "simular" and not hasattr(args, "segundos"):
        args.segundos, args.sem_navegador = 20, False
    acoes = {"escola": cmd_escola, "backtest": cmd_escola, "simular": cmd_simular, "painel": cmd_painel, "zerar": cmd_zerar}
    if cmd not in acoes:
        print("Opção inválida.")
        return
    try:
        acoes[cmd](args)
    except KeyboardInterrupt:
        print("\n👋 Agência fechada. Tudo salvo — rode de novo pra continuar.")


if __name__ == "__main__":
    main()
