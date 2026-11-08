"""Servidorzinho local (só no seu PC) que mostra o escritório 3D e o painel no navegador."""
import http.server
import json
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

import gerente

AQUI = Path(__file__).resolve().parent
DADOS = AQUI / "dados"
ARQ_SIM = DADOS / "simulacao.json"
ARQ_ESCOLA = DADOS / "escola.json"
ARQ_LOG_ESCOLA = DADOS / "escola_log.txt"

_estado = {"fila": None, "processo_escola": None, "arquivo_sim": ARQ_SIM}


def _ler_json(arq):
    try:
        return json.loads(Path(arq).read_text(encoding="utf-8"))
    except Exception:
        return None


def _reduzir(curva, n=400):
    if not curva or len(curva) <= n:
        return curva
    passo = len(curva) / n
    return [curva[int(k * passo)] for k in range(n)] + [curva[-1]]


def enxugar(d):
    """Manda pro navegador só o necessário (o arquivo completo fica no disco)."""
    d["eventos"] = d.get("eventos", [])[-150:]
    d["curva"] = _reduzir(d.get("curva"))
    for tm in d.get("times", []):
        tm["curva"] = _reduzir(tm.get("curva"))
    for tr in d.get("traders", []):
        tr["trades"] = tr.get("trades", [])[-15:]
    return d


def escola_rodando():
    p = _estado["processo_escola"]
    return p is not None and p.poll() is None


def rodar_escola_em_segundo_plano():
    if escola_rodando():
        return False
    DADOS.mkdir(exist_ok=True)
    log = open(ARQ_LOG_ESCOLA, "w", encoding="utf-8")
    _estado["processo_escola"] = subprocess.Popen(
        [sys.executable, "-u", str(AQUI / "rodar.py"), "escola"], cwd=str(AQUI),
        stdout=log, stderr=subprocess.STDOUT, env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    return True


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _responder(self, codigo, corpo, tipo="application/json; charset=utf-8"):
        if isinstance(corpo, (dict, list)):
            corpo = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _pagina(self, nome):
        arq = AQUI / nome
        if not arq.exists():
            arq = AQUI / "painel.html"
        self._responder(200, arq.read_bytes(), "text/html; charset=utf-8")

    def do_GET(self):
        caminho = self.path.split("?")[0]
        if caminho == "/api/estado":
            d = _ler_json(_estado["arquivo_sim"])
            if d is None:
                return self._responder(200, {"vazio": True})
            d = enxugar(d)
            g = gerente.carregar()
            d["gerente"] = {"relatorio": g.get("relatorio")}
            d["simulacao_rodando"] = _estado["fila"] is not None
            return self._responder(200, d)
        if caminho == "/api/escola":
            d = _ler_json(ARQ_ESCOLA) or {"vazio": True}
            d["rodando"] = escola_rodando()
            if ARQ_LOG_ESCOLA.exists():
                d["log"] = ARQ_LOG_ESCOLA.read_text(encoding="utf-8", errors="replace").splitlines()[-12:]
            return self._responder(200, d)
        if caminho == "/api/gerente":
            ok, motivo = gerente.status()
            g = gerente.carregar()
            return self._responder(200, {"disponivel": ok, "motivo": motivo, "modelo": gerente.MODELO, "chave": gerente.mascara(), **g})
        if caminho in ("/", "/escritorio"):
            return self._pagina("escritorio.html")
        if caminho in ("/painel", "/index.html"):
            return self._pagina("painel.html")
        self._responder(404, b"nao encontrado", "text/plain")

    def do_POST(self):
        caminho = self.path.split("?")[0]
        try:
            tam = int(self.headers.get("Content-Length") or 0)
            corpo = json.loads(self.rfile.read(tam).decode("utf-8") or "{}")
        except Exception:
            return self._responder(400, {"erro": "pedido inválido"})

        if caminho == "/api/comando":
            if _estado["fila"] is None:
                return self._responder(200, {"ok": False, "erro": "A simulação não está rodando. Abra com: python rodar.py simular"})
            _estado["fila"].put(corpo)
            return self._responder(200, {"ok": True, "msg": "Pedido enviado! Aplico na próxima checagem (alguns segundos)."})

        if caminho == "/api/escola/rodar":
            iniciou = rodar_escola_em_segundo_plano()
            return self._responder(200, {"ok": iniciou, "msg": "A escola começou as provas!" if iniciou else "A escola já está rodando."})

        if caminho == "/api/gerente/chave":
            chave = (corpo.get("chave") or "").strip()
            if not chave.startswith("sk-"):
                return self._responder(200, {"ok": False, "erro": "Essa não parece uma chave de API da Anthropic (começa com sk-ant-)."})
            gerente.salvar_chave(chave)
            gerente.limpar_erro()
            return self._responder(200, {"ok": True})

        if caminho == "/api/gerente/testar":
            try:
                import anthropic  # noqa: F401
            except ImportError:
                return self._responder(200, {"ok": False, "texto": "Falta instalar a biblioteca: dê dois cliques em 3_instalar_gerente.bat e reinicie a agência.", "rede": []})
            return self._responder(200, gerente.testar())

        if caminho in ("/api/gerente/perguntar", "/api/gerente/relatorio"):
            ok, motivo = gerente.status()
            if not ok:
                return self._responder(200, {"ok": False, "erro": motivo})
            estado, escola = _ler_json(_estado["arquivo_sim"]), _ler_json(ARQ_ESCOLA)
            try:
                if caminho.endswith("perguntar"):
                    pergunta = (corpo.get("pergunta") or "").strip()[:2000]
                    if not pergunta:
                        return self._responder(200, {"ok": False, "erro": "Escreva uma pergunta."})
                    texto = gerente.perguntar(pergunta, estado, escola)
                else:
                    texto = gerente.gerar_relatorio(estado, escola)
                return self._responder(200, {"ok": True, "texto": texto})
            except Exception as e:
                gerente.registrar_erro(str(e))
                return self._responder(200, {"ok": False, "erro": str(e)})

        self._responder(404, {"erro": "não encontrado"})


def iniciar(arquivo_sim=ARQ_SIM, fila=None, porta=8000, abrir_navegador=True, bloquear=False):
    _estado["fila"] = fila
    _estado["arquivo_sim"] = arquivo_sim
    servidor = None
    for p in range(porta, porta + 20):
        try:
            servidor = http.server.ThreadingHTTPServer(("127.0.0.1", p), Handler)
            break
        except OSError:
            continue
    if servidor is None:
        raise SystemExit("Não achei nenhuma porta livre entre 8000 e 8019.")
    url = f"http://127.0.0.1:{servidor.server_address[1]}"
    print(f"🖥️  Escritório e painel em {url}  (painel: {url}/painel)")
    if abrir_navegador:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    if bloquear:
        try:
            servidor.serve_forever()
        except KeyboardInterrupt:
            print("\nPainel fechado.")
    else:
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return url
