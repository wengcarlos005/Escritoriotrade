"""SINCRONIA ENTRE PCs: a mesma simulação no PC do trabalho, no de casa, em qualquer um.

Como funciona:
  • Os dados da agência (simulação e boletins da escola) ficam guardados num repositório PRIVADO seu no GitHub
    (`escritoriotrade-dados`), além da pasta dados/ do PC.
  • Ao ligar a agência, ela baixa de lá a versão mais nova (a que foi salva por último, em qualquer PC).
  • Enquanto roda, ela manda a versão atual pra lá a cada poucos minutos e ao fechar.
  • O tempo em que nenhum PC ficou ligado não se perde: ao abrir, a agência refaz vela por vela tudo o que
    aconteceu no mercado desde o último salvamento, como se nunca tivesse parado.
  • Sem internet: continua normal com os dados do PC e sincroniza quando a conexão voltar.

Regra de ouro: deixe a agência aberta em UM PC por vez (vale o que foi salvo por último).
A chave do gerente (Claude) e o config.json NÃO vão pro GitHub.
"""
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
DADOS = AQUI / "dados"
PASTA = DADOS / "sincronia"
ARQUIVOS = ["simulacao.json", "escola.json", "escola_agencia.json"]
PC = socket.gethostname() or "PC"
_trava = threading.Lock()
_ultimo_envio = [0.0]
_conhecido = {"remoto": None, "avisou": False}   # a última versão da nuvem que este PC conhece (pra nunca apagar a de outro PC)


def _cfg(cfg):
    return (cfg or {}).get("sincronizar") or {}


def ativo(cfg):
    c = _cfg(cfg)
    return bool(c.get("ativo") and c.get("repo"))


def _git(*args, timeout=90, interativo=False):
    env = dict(os.environ)
    if not interativo:
        env["GIT_TERMINAL_PROMPT"] = "0"   # rodando sozinho: nunca trava esperando senha
    try:
        return subprocess.run(["git", *args], capture_output=not interativo, text=True, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired) as erro:
        return subprocess.CompletedProcess(args, 1, "", str(erro))


def _carimbo(arq):
    """Quando o arquivo foi salvo (pelo próprio conteúdo): salvo_em da simulação ou gerado_em dos boletins."""
    try:
        d = json.loads(Path(arq).read_text(encoding="utf-8"))
        return int(d.get("salvo_em") or d.get("gerado_em") or 0)
    except Exception:
        return 0


def _quando(ms):
    return time.strftime("%d/%m %H:%M", time.localtime(ms / 1000)) if ms else "?"


def repo_padrao():
    """O repositório de dados fica na mesma conta do GitHub do código: <dono>/escritoriotrade-dados."""
    r = _git("-C", str(AQUI), "remote", "get-url", "origin")
    url = (r.stdout or "").strip() if r.returncode == 0 else ""
    if "github.com" in url:
        dono = url.rstrip("/").replace(".git", "").replace(":", "/").split("/")[-2]
        return f"https://github.com/{dono}/escritoriotrade-dados.git"
    return None


def _preparar_pasta(repo, avisar):
    if (PASTA / ".git").exists():
        r = _git("-C", str(PASTA), "fetch", "-q", "origin")
        if r.returncode != 0:
            return False
        tem_main = _git("-C", str(PASTA), "rev-parse", "--verify", "-q", "origin/main").returncode == 0
        if tem_main:
            _git("-C", str(PASTA), "checkout", "-q", "-B", "main", "origin/main")
            _git("-C", str(PASTA), "reset", "-q", "--hard", "origin/main")
        return True
    PASTA.parent.mkdir(exist_ok=True)
    if PASTA.exists():
        shutil.rmtree(PASTA, ignore_errors=True)
    r = _git("clone", "-q", repo, str(PASTA), timeout=180)
    if r.returncode != 0:
        return False
    if _git("-C", str(PASTA), "rev-parse", "--verify", "-q", "origin/main").returncode == 0:
        _git("-C", str(PASTA), "checkout", "-q", "-B", "main", "origin/main")
    return True


def baixar(cfg, avisar=print):
    """Ao ligar: traz da nuvem o que for mais novo que o deste PC."""
    if not ativo(cfg):
        return
    with _trava:
        if not _preparar_pasta(_cfg(cfg)["repo"], avisar):
            _conhecido["remoto"] = _carimbo(DADOS / "simulacao.json")   # offline: só sobrescreve a nuvem se ela não andou
            avisar("☁️  Sem acesso à nuvem agora (sem internet ou o GitHub não respondeu) — continuo com os dados deste PC.")
            return
        _conhecido["remoto"] = _carimbo(PASTA / "simulacao.json")
        uso = PASTA / "em_uso.json"
        if uso.exists():
            try:
                u = json.loads(uso.read_text(encoding="utf-8"))
                minutos = (time.time() * 1000 - u.get("ultimo", 0)) / 60000
                if u.get("pc") != PC and u.get("aberta") and minutos < 20:
                    avisar(f"⚠️  A agência parece estar ABERTA no PC '{u.get('pc')}' (último sinal há {minutos:.0f} min). "
                           "Feche lá: se os dois ficarem abertos, vale o que salvar por último.")
            except Exception:
                pass
        for nome in ARQUIVOS:
            remoto, local = PASTA / nome, DADOS / nome
            if remoto.exists() and _carimbo(remoto) > _carimbo(local):
                DADOS.mkdir(exist_ok=True)
                shutil.copy2(remoto, local)
                if nome == "simulacao.json":
                    avisar(f"☁️  Continuando de onde parou: trouxe a simulação salva em {_quando(_carimbo(remoto))} "
                           f"(a agência vai recuperar o que aconteceu no mercado desde então).")


def enviar(cfg, avisar=print, final=False):
    """Manda a versão atual pra nuvem (em segundo plano a cada poucos minutos; e ao fechar)."""
    if not ativo(cfg) or not _trava.acquire(blocking=final):
        return False
    try:
        if not _preparar_pasta(_cfg(cfg)["repo"], avisar):   # olha a nuvem antes de mandar
            return False
        remoto = _carimbo(PASTA / "simulacao.json")
        if _conhecido["remoto"] is not None and remoto > _conhecido["remoto"]:
            # outro PC salvou na nuvem DEPOIS que este abriu: não apaga o progresso dele
            if not _conhecido["avisou"] or final:
                _conhecido["avisou"] = True
                avisar(f"⚠️  Outro PC salvou a simulação na nuvem ({_quando(remoto)}) depois que este abriu. Pra não apagar o progresso "
                       "dele, este PC NÃO vai mandar a dele. Feche a agência aqui e abra de novo pra continuar da versão mais nova.")
            return False
        mudou = False
        for nome in ARQUIVOS:
            local, remoto = DADOS / nome, PASTA / nome
            if local.exists() and (not remoto.exists() or _carimbo(local) >= _carimbo(remoto)):
                shutil.copy2(local, remoto)
                mudou = True
        agora = int(time.time() * 1000)
        (PASTA / "em_uso.json").write_text(json.dumps({"pc": PC, "ultimo": agora, "aberta": not final}), encoding="utf-8")
        (PASTA / "LEIA.md").write_text("Dados da Agência de Trade (sincronia entre PCs). Não edite à mão.\n", encoding="utf-8")
        # guarda só a ÚLTIMA versão (um commit só, substituído a cada envio): o repositório não cresce com o tempo
        g = lambda *a, **k: _git("-C", str(PASTA), *a, **k)
        g("checkout", "-q", "--orphan", "nova")
        g("add", "-A")
        g("-c", "user.name=Agencia de Trade", "-c", "user.email=agencia@localhost",
          "commit", "-q", "-m", f"{PC} · {_quando(agora)}" + (" · fechou" if final else ""))
        g("branch", "-q", "-D", "main")
        g("branch", "-q", "-m", "main")
        r = g("push", "-q", "--force", "origin", "main", timeout=120)
        g("reflog", "expire", "--expire=now", "--all")
        g("gc", "-q", "--prune=now")
        _ultimo_envio[0] = time.time()
        if r.returncode == 0:
            _conhecido["remoto"] = _carimbo(PASTA / "simulacao.json")
        if r.returncode != 0 and final:
            avisar("☁️  Não consegui mandar pra nuvem agora (sem internet?). Os dados ficaram salvos neste PC e sobem na próxima vez.")
        elif final and mudou:
            avisar("☁️  Simulação guardada na nuvem: pode abrir em outro PC que continua de onde parou.")
        return r.returncode == 0
    finally:
        _trava.release()


def talvez_enviar(cfg, avisar=print):
    """Chamado a cada salvamento: manda pra nuvem em segundo plano se já passou o intervalo."""
    if not ativo(cfg):
        return
    if time.time() - _ultimo_envio[0] >= _cfg(cfg).get("a_cada_minutos", 5) * 60:
        _ultimo_envio[0] = time.time()
        threading.Thread(target=enviar, args=(cfg, avisar), daemon=True).start()


def ligar(salvar_config, cfg_usuario, avisar=print):
    """Configura a sincronia neste PC (rodar uma vez em cada PC): python rodar.py sincronia"""
    repo = _cfg(cfg_usuario).get("repo") or repo_padrao()
    if not repo:
        avisar("Não achei o endereço do GitHub desta pasta. Rode antes o conectar_ao_github.bat.")
        return False
    avisar(f"☁️  Testando o acesso a {repo} (na 1ª vez o navegador pode abrir pra você entrar no GitHub)...")
    if _git("ls-remote", repo, timeout=300, interativo=True).returncode != 0:
        avisar("❌ Não consegui acessar. Confira se você criou o repositório PRIVADO 'escritoriotrade-dados' (vazio) "
               "na sua conta do GitHub e se entrou com a conta certa. Depois rode de novo.")
        return False
    cfg_usuario.setdefault("sincronizar", {}).update({"ativo": True, "repo": repo})
    salvar_config(cfg_usuario)
    baixar(cfg_usuario, avisar)
    enviar(cfg_usuario, avisar, final=True)
    avisar("✅ Sincronia ligada neste PC. Faça o mesmo no outro PC e pronto: a agência continua de onde parou em qualquer um.")
    return True
