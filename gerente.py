"""O gerente da agência: o Claude de verdade, pela API da Anthropic.

Ele lê o estado da simulação e o boletim da Escola de Traders e:
  • escreve um relatório diário (o que aconteceu, riscos, recomendações pro CEO);
  • responde perguntas do CEO no painel.
Ele NÃO opera nem muda nada sozinho: quem decide é você (o CEO), pelo painel.

Precisa de: `pip install anthropic` e uma chave de API (https://console.anthropic.com),
colada pelo painel (fica salva em dados/claude_api_key.txt) ou na variável ANTHROPIC_API_KEY.
"""
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

AQUI = Path(__file__).resolve().parent
ARQ = AQUI / "dados" / "gerente.json"
ARQ_CHAVE = AQUI / "dados" / "claude_api_key.txt"
MODELO = "claude-opus-5-5"
FUSO = timezone(timedelta(hours=-3))
_trava = threading.Lock()

SISTEMA = """Você é o Claude, gerente da "Agência de Trade": uma agência fictícia de robôs que operam cripto na \
Binance com DINHEIRO DE MENTIRA (simulação com preços reais). O dono (o "CEO") é o usuário, que está aprendendo e quer, \
no futuro, lucrar de verdade. A agência é uma LIGA de 5 times: cada time é uma estratégia da Escola de Traders (alunos = \
estratégias inspiradas em traders famosos, avaliadas com walk-forward fora da amostra, custos e Deflated Sharpe) com 5 \
traders robôs, um por moeda. Toda segunda o melhor time das últimas 4 semanas vira titular; bebês traders nascem a cada \
R$ 500 de lucro de um time.

Seu papel:
- Ser o gerente honesto e disciplinado: explicar o que aconteceu com números, apontar riscos e dar recomendações claras.
- Proteger o CEO de autoengano: lembrar que backtest não garante futuro, que o período avaliado pode favorecer certas \
estratégias, que comprar-e-segurar é a régua, e que resultado de poucos dias de simulação é ruído.
- Quando comentar a disputa entre os times ou recomendar uma nova temporada, justifique com as métricas da escola (Sharpe, queda máxima, \
consistência, custo dobrado, confiança DSR) e diga o que poderia dar errado.
- Nunca prometa lucro. Não dê recomendação de investimento personalizada com dinheiro real; se o CEO falar em \
dinheiro real, recomende antes meses de simulação, valores pequenos, chave de API sem permissão de saque e as travas.

Estilo: português do Brasil, simples (o CEO não é especialista), simpático e direto, com um toque de humor de \
"escritório" (pode citar o mascote). Use markdown leve (títulos curtos ##, listas, **negrito**). Seja breve."""


# ---------------------------------------------------------------------------
def _chave():
    if ARQ_CHAVE.exists():
        k = ARQ_CHAVE.read_text(encoding="utf-8").strip()
        if k:
            return k
    return os.environ.get("ANTHROPIC_API_KEY")


def salvar_chave(chave):
    ARQ_CHAVE.parent.mkdir(exist_ok=True)
    ARQ_CHAVE.write_text(chave.strip(), encoding="utf-8")


def mascara():
    k = _chave()
    return (k[:10] + "…" + k[-4:]) if k and len(k) > 16 else None


def limpar_erro():
    g = carregar()
    g["erro"] = None
    _salvar(g)


def testar():
    """Teste rápido pelo painel: rede + uma perguntinha curta. Devolve dict."""
    rede = [{"ok": ok, "texto": t} for ok, t in diagnostico_rede()]
    k = _chave() or ""
    aviso = None
    if k and not k.startswith("sk-ant-api"):
        aviso = ("As chaves de console.anthropic.com → API Keys normalmente começam com 'sk-ant-api'. "
                 "Se der 'chave recusada', crie uma chave nova lá.")
    try:
        resp = _chamar([{"role": "user", "content": "Responda só: 'Olá, CEO! Estou conectado.'"}])
        limpar_erro()
        # deu certo: o que parecia problema na rede foi contornado — vira só informação
        rede = [{"ok": None if x["ok"] is False else x["ok"],
                 "texto": x["texto"].split(". Se você não usa")[0] + " — o gerente ignora isso e fala direto com a Anthropic."
                 if "variável de ambiente" in x["texto"] else x["texto"]} for x in rede]
        return {"ok": True, "texto": resp, "rede": rede, "aviso": None}
    except Exception as e:
        return {"ok": False, "texto": str(e), "rede": rede, "aviso": aviso}


def status():
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False, "sem_biblioteca"
    if not _chave() and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return False, "sem_chave"
    return True, "ok"


def carregar():
    if ARQ.exists():
        try:
            return json.loads(ARQ.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"relatorio": None, "conversa": [], "erro": None}


def _salvar(g):
    ARQ.parent.mkdir(exist_ok=True)
    tmp = ARQ.with_suffix(".tmp")
    tmp.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, ARQ)


# ---------------------------------------------------------------------------
def _h(t):
    return datetime.fromtimestamp(t / 1000, FUSO).strftime("%d/%m %H:%M")


def contexto(estado, escola):
    """Resumo compacto dos dados pro gerente ler."""
    linhas = []
    if estado and not estado.get("vazio"):
        brl = estado.get("cotacao_brl") or 5.5

        def patr(t):
            return t["caixa"] + (t["posicao"]["qtd"] * (t.get("ultimo_preco") or t["posicao"]["preco"]) if t.get("posicao") else 0)

        temp = estado.get("temporada") or {}
        total = sum(patr(t) for t in estado["traders"])
        linhas.append(f"# Liga ao vivo — temporada {temp.get('numero')} (começou {_h(temp.get('inicio', 0))}; agora {_h(int(time.time() * 1000))}; "
                      f"próxima rodada {_h(temp.get('proxima_rodada', 0))})")
        linhas.append("Regras: 5 times, cada um = 1 estratégia da escola com 5 traders (BTC, ETH, SOL, BNB, XRP, US$ 100 cada). "
                      "Toda segunda o time com melhor pontuação (retorno 4 semanas − metade da maior queda) vira TITULAR "
                      "(o que operaria com dinheiro real no futuro); os outros ficam na reserva. Bebês nascem a cada R$ 500 de lucro do time.")
        linhas.append(f"Dólar: R$ {brl:.2f}. Patrimônio total: US$ {total:.2f} (colocado: US$ {estado['aportes_ceo']:.2f}).")
        for tm in sorted(estado.get("times", []), key=lambda x: x.get("lugar") or 9):
            papel = "TITULAR" if tm["titular"] else ("MESA RÁPIDA, fora da disputa (velas curtas — serve pra mostrar o efeito das taxas)" if tm.get("especial") else "reserva")
            linhas.append(f"## {tm['lugar'] or '–'}º {papel}: {tm['emoji']} {tm['nome']} "
                          f"({tm['estrategia_nome']}, {tm['intervalo']}, nota na escola {tm.get('nota_escola')}) — patrimônio US$ {tm['patrimonio']:.2f} "
                          f"({tm['resultado_pct']:+.2f}%), pontuação 4 semanas {tm.get('pontuacao_agora')}, bebês {tm['bebes']}, "
                          f"rumo ao próximo bebê {tm['meta_bebe_pct']}%")
            for t in [x for x in estado["traders"] if x.get("time") == tm["id"]]:
                pos = "sem posição"
                if t.get("posicao"):
                    p = t["posicao"]
                    var = ((t.get("ultimo_preco") or p["preco"]) / p["preco"] - 1) * 100
                    pos = f"comprado desde {_h(p['t'])} ({var:+.2f}%)"
                linhas.append(f"- {t['nome']}: US$ {patr(t):.2f}, lucro realizado US$ {t['lucro_realizado']:+.2f}, "
                              f"{t['vitorias']}V/{t['derrotas']}D, {pos}")
        sp = estado.get("sprint_atual")
        if sp:
            tt = sp["total"]
            linhas.append(f"Sprint {sp['numero']} (dia {sp['dias']} de 7): {tt['operacoes']} operações dos times, resultado {tt['lucro_pct']:+.2f}%, "
                          f"taxas US$ {tt['taxas']:.2f}, girou US$ {tt['volume']:.0f}, comprado {tt['exposicao_pct']}% do tempo. "
                          "Metas: " + "; ".join(f"{m['meta']} → {m['valor']} {'OK' if m['ok'] else 'NÃO'}" for m in sp["metas"]))
        for r in temp.get("rodadas", [])[-4:]:
            linhas.append(f"Rodada {_h(r['t'])}: vencedor {r['vencedor']} — " +
                          ", ".join(f"{x['id']} {x['pontuacao']:+.2f}" for x in r["ranking"]))
        linhas.append("Últimos eventos:")
        for e in estado.get("eventos", [])[-25:]:
            linhas.append(f"- [{_h(e['t'])}] {e['texto']}")
    if escola:
        r0, r1 = escola["periodo_oos"]
        refs = escola.get("referencias", {})
        s, d = refs.get("segurar", {}), refs.get("dca", {})
        linhas.append(f"\n# Boletim da Escola (gerado {_h(escola['gerado_em'])}; provas fora da amostra de {_h(r0)} a {_h(r1)}, "
                      f"{escola['resultados'][0]['par'] if escola['resultados'] else ''}, {escola['alunos_testados']} alunos, "
                      f"{escola['combinacoes_testadas']} combinações)")
        linhas.append(f"Referências no mesmo período: comprar e segurar {s.get('retorno_pct')}% (queda máx {s.get('max_dd_pct')}%, "
                      f"Sharpe {s.get('sharpe')}); DCA semanal {d.get('retorno_pct')}% (queda máx {d.get('max_dd_pct')}%).")
        for k, r in enumerate(escola["resultados"], 1):
            o = r["oos"]
            linhas.append(f"{k}. {r['emoji']} {r['nome']} ({r['inspiracao']}; {r['intervalo']}) nota {r['nota']} "
                          f"{'APROVADA' if r['aprovada'] else 'reprovada: ' + '; '.join(r['motivos'])} | "
                          f"retorno {o['retorno_pct']}%, CAGR {o['cagr_pct']}%, queda máx {o['max_dd_pct']}%, Sharpe {o['sharpe']}, "
                          f"PF {o['profit_factor']}, {o['trades']} ops, consistência {o['consistencia_pct']}%, "
                          f"custo dobrado {o['retorno_custo_dobrado_pct']}%, confiança DSR {o.get('dsr')}, exposição {o['exposicao_pct']}%")
    return "\n".join(linhas) or "(sem dados ainda)"


def _usar_certificados_do_windows():
    """Antivírus (Avast, Kaspersky, ESET...) e proxies costumam inspecionar HTTPS com um certificado próprio
    que só existe na lista do Windows. Com o pacote `truststore`, o Python passa a usar essa lista."""
    try:
        import truststore
        truststore.inject_into_ssl()
        return True
    except Exception:
        return False


_TRUSTSTORE = _usar_certificados_do_windows()


API_OFICIAL = "https://api.anthropic.com"
_DIRETO = {"usar": False}  # vira True se o caminho "normal" do Windows estiver quebrado


def _cliente(direto=False):
    """direto=True ignora variáveis de proxy/endereço do Windows e fala com a API oficial."""
    import anthropic
    k = _chave()
    extra = {"api_key": k} if k else {}
    if direto:
        return anthropic.Anthropic(base_url=API_OFICIAL, timeout=120.0, http_client=anthropic.DefaultHttpxClient(trust_env=False), **extra)
    return anthropic.Anthropic(base_url=API_OFICIAL, timeout=120.0, **extra)


def diagnostico_rede():
    """Descobre por que a conexão com a Anthropic falha. Devolve lista de (ok, texto)."""
    import socket
    import urllib.request
    achados = []
    for var in ("ANTHROPIC_BASE_URL", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        if os.environ.get(var) and not os.environ[var].rstrip("/").startswith(API_OFICIAL):
            achados.append((False, f"A variável de ambiente {var} está definida como '{os.environ[var]}'. "
                                   "Se você não usa esse proxy/endereço, apague essa variável (Windows: Configurações → Sistema → Sobre → "
                                   "Configurações avançadas → Variáveis de ambiente) e reinicie o computador."))
    try:
        ips = sorted({x[4][0] for x in socket.getaddrinfo("api.anthropic.com", 443)})
        locais = [ip for ip in ips if ip.startswith(("127.", "0.", "::1")) or ip in ("::", "0:0:0:0:0:0:0:1")]
        if locais:
            achados.append((False, f"O seu PC está mandando api.anthropic.com para {', '.join(locais)} (o próprio computador). "
                                   "Isso é o arquivo HOSTS bloqueando (bloqueador de anúncios/telemetria). Abra o Bloco de Notas como "
                                   "administrador, abra C:\\Windows\\System32\\drivers\\etc\\hosts e apague (ou ponha # na frente de) "
                                   "as linhas com 'anthropic'. Salve e tente de novo."))
        else:
            achados.append((True, f"api.anthropic.com → {', '.join(ips)} (endereço normal)"))
            try:
                with socket.create_connection((ips[0], 443), timeout=8):
                    achados.append((True, "Conexão direta na porta 443: OK"))
            except Exception as e:
                achados.append((False, f"Conexão direta na porta 443 falhou ({e}). Algum firewall/antivírus/VPN está bloqueando o python.exe. "
                                       "Libere o Python no firewall (ou desligue a VPN) e tente de novo."))
    except Exception as e:
        achados.append((False, f"O PC não conseguiu descobrir o endereço de api.anthropic.com ({e}). Confira a internet/DNS."))
    proxies = {k: v for k, v in urllib.request.getproxies().items() if k in ("http", "https", "all")}
    if proxies:
        achados.append((None, f"Proxies configurados no Windows: {proxies}"))
    return achados


def _causa(e):
    """O motivo verdadeiro escondido dentro de um erro de conexão."""
    partes, atual = [], e
    for _ in range(5):
        atual = atual.__cause__ or atual.__context__
        if atual is None:
            break
        partes.append(f"{type(atual).__name__}: {atual}")
    texto = " | ".join(partes)
    return texto[:400] if texto else str(e)


def _pedir(cliente, mensagens):
    return cliente.beta.messages.create(
        model=MODELO,
        max_tokens=16000,
        system=SISTEMA,
        messages=mensagens,
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        extra_body={"fallbacks": "default"},
    )


def _chamar(mensagens):
    import anthropic
    try:
        try:
            resp = _pedir(_cliente(direto=_DIRETO["usar"]), mensagens)
        except anthropic.APIConnectionError:
            if _DIRETO["usar"]:
                raise
            # tenta de novo ignorando proxy/variáveis do Windows (às vezes apontam pra algo desligado)
            resp = _pedir(_cliente(direto=True), mensagens)
            _DIRETO["usar"] = True
    except anthropic.AuthenticationError:
        raise RuntimeError("A chave de API foi recusada. Confira se colou a chave certa.")
    except anthropic.PermissionDeniedError:
        raise RuntimeError("A chave não tem permissão pra usar esse modelo.")
    except anthropic.RateLimitError:
        raise RuntimeError("Muitos pedidos ou créditos esgotados. Tente de novo daqui a pouco e confira seus créditos no console da Anthropic.")
    except anthropic.APIConnectionError as e:
        causa = _causa(e)
        if "CERTIFICATE" in causa.upper() or "SSL" in causa.upper():
            dica = ("Parece o antivírus/proxy inspecionando a conexão. Dê dois cliques em 3_instalar_gerente.bat "
                    "(instala o 'truststore', que faz o Python usar os certificados do Windows) e reinicie a agência.")
        elif "timed out" in causa.lower() or "timeout" in causa.lower():
            dica = "A conexão demorou demais. Tente de novo; se repetir, confira firewall/antivírus bloqueando o python.exe."
        else:
            dica = "Confira se algum firewall/antivírus está bloqueando o python.exe (api.anthropic.com)."
        problemas = [t for ok, t in diagnostico_rede() if ok is False]
        if problemas:
            dica = " ".join(problemas)
        raise RuntimeError(f"Sem conexão com a Anthropic. {dica} (Detalhe técnico: {causa})")
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Erro da API ({e.status_code}): {e.message}")
    if resp.stop_reason == "refusal":
        return "Desculpe, CEO — não posso responder isso. Pergunta de outro jeito?"
    texto = "".join(b.text for b in resp.content if b.type == "text").strip()
    if resp.stop_reason == "max_tokens":
        texto += "\n\n_(resposta cortada por tamanho)_"
    return texto or "(o gerente ficou sem palavras)"


def gerar_relatorio(estado, escola):
    """Escreve o relatório do dia. Devolve o texto (ou levanta RuntimeError)."""
    pedido = (contexto(estado, escola) + "\n\n---\nEscreva o RELATÓRIO DO GERENTE de hoje para o CEO, com estas seções: "
              "## Resumo do dia (2–3 frases), ## A liga (titular, quem subiu e quem caiu, bebês), ## Escola de traders "
              "(o que o boletim diz, se vale começar nova temporada), "
              "## Riscos e alertas, ## Minha recomendação (no máximo 3 itens práticos). Máximo ~350 palavras.")
    with _trava:
        texto = _chamar([{"role": "user", "content": pedido}])
        g = carregar()
        g["relatorio"] = {"t": int(time.time() * 1000), "texto": texto}
        g["erro"] = None
        _salvar(g)
    return texto


def gerar_retro(sprint, escola):
    """Retrospectiva da sprint: o que funcionou, o que não, e o que testar na próxima."""
    dados = json.dumps({k: v for k, v in sprint.items() if k != "times"} | {"times": sprint["times"]}, ensure_ascii=False)
    pedido = ("Esta é a RETROSPECTIVA de uma sprint (1 semana) da liga simulada. Dados da sprint em JSON:\n" + dados +
              "\n\nResumo do boletim da escola pra contexto:\n" + contexto(None, escola)[:3000] +
              "\n\n---\nEscreva a retrospectiva pro CEO com estas seções: ## O que aconteceu (3 frases com números), "
              "## O que funcionou, ## O que não funcionou (inclua o peso das taxas e o tempo parado), "
              "## Próxima sprint: 3 experimentos concretos (o que mudar, como medir, qual meta). Máximo ~300 palavras.")
    with _trava:
        texto = _chamar([{"role": "user", "content": pedido}])
        g = carregar()
        g.setdefault("retros", {})[str(sprint["numero"])] = {"t": int(time.time() * 1000), "texto": texto}
        _salvar(g)
    return texto


def perguntar(pergunta, estado, escola):
    with _trava:
        g = carregar()
        mensagens = []
        for c in g.get("conversa", [])[-6:]:
            mensagens += [{"role": "user", "content": c["pergunta"]}, {"role": "assistant", "content": c["resposta"]}]
        mensagens.append({"role": "user", "content":
                          "Dados atuais da agência (só para consulta):\n" + contexto(estado, escola)
                          + "\n\n---\nPergunta do CEO: " + pergunta})
        resposta = _chamar(mensagens)
        g.setdefault("conversa", []).append({"t": int(time.time() * 1000), "pergunta": pergunta, "resposta": resposta})
        g["conversa"] = g["conversa"][-30:]
        _salvar(g)
    return resposta


def registrar_erro(msg):
    g = carregar()
    g["erro"] = {"t": int(time.time() * 1000), "texto": msg}
    _salvar(g)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Diagnóstico: python gerente.py  (ou 5_testar_gerente.bat)
    import platform
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("🔎 Testando o gerente...\n")
    print(f"Python {platform.python_version()} em {platform.system()} {platform.release()}")
    try:
        import anthropic
        print(f"Biblioteca anthropic {anthropic.__version__}: OK")
    except ImportError:
        print("❌ Falta a biblioteca: dê dois cliques em 3_instalar_gerente.bat")
        sys.exit(1)
    print("Certificados do Windows (truststore):", "OK, em uso" if _TRUSTSTORE else "não instalado (rode 3_instalar_gerente.bat)")
    k = _chave()
    print("Chave:", (k[:10] + "…" + k[-4:]) if k else "❌ nenhuma (cole na aba Gerente do painel)")
    if not k:
        sys.exit(1)
    if not k.startswith("sk-ant-api"):
        print("⚠️  As chaves criadas em console.anthropic.com → API Keys normalmente começam com 'sk-ant-api'. "
              "A sua começa diferente — se der 'chave recusada', crie uma chave nova lá e cole na aba Gerente.")
    print("\nRede:")
    for ok, texto in diagnostico_rede():
        print("  " + ("✅" if ok else "❌" if ok is False else "ℹ️ ") + " " + texto)
    try:
        print("\nPerguntando ao Claude...")
        print("✅ Resposta:", _chamar([{"role": "user", "content": "Diga 'olá, CEO!' em uma frase curta."}]))
    except Exception as e:
        print("❌", e)
        sys.exit(1)
