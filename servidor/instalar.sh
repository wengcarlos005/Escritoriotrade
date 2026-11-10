#!/usr/bin/env bash
# Instala a Agência de Trade num servidor Ubuntu/Debian na nuvem: ligada 24h, com HTTPS e senha.
# Uso (logado como root no servidor):
#   curl -fsSL https://raw.githubusercontent.com/wengcarlos005/escritoriotrade/main/servidor/instalar.sh | bash
# Pode rodar de novo quando quiser (mantém os dados e a senha).
set -euo pipefail
REPO="${REPO:-https://github.com/wengcarlos005/escritoriotrade.git}"
PASTA="${PASTA:-/opt/agencia}"
USUARIO=agencia
[ "$(id -u)" = 0 ] || { echo "Rode como root (ou com sudo)."; exit 1; }
export DEBIAN_FRONTEND=noninteractive

echo "==> 1/7 Instalando os programas (Python, Git, Caddy)..."
apt-get update -y -q
apt-get install -y -q python3 git curl ca-certificates
if ! command -v caddy >/dev/null 2>&1; then
  if ! apt-get install -y -q caddy; then
    apt-get install -y -q debian-keyring debian-archive-keyring apt-transport-https gnupg
    curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt -o /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -y -q
    apt-get install -y -q caddy
  fi
fi

echo "==> 2/7 Conferindo se a Binance responde daqui..."
codigo=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 https://fapi.binance.com/fapi/v1/time || echo 000)
if [ "$codigo" = "451" ] || [ "$codigo" = "403" ]; then
  echo "    ⚠️  A Binance BLOQUEIA este servidor (código $codigo) — provavelmente ele está nos EUA."
  echo "       A agência vai funcionar com o preço à vista (aproximação). Melhor: criar o servidor na Europa ou no Brasil."
else
  echo "    ok (código $codigo)"
fi

echo "==> 3/7 Baixando a agência do GitHub..."
id -u "$USUARIO" >/dev/null 2>&1 || useradd --system --create-home --home-dir "/home/$USUARIO" --shell /usr/sbin/nologin "$USUARIO"
if [ -d "$PASTA/.git" ]; then
  runuser -u "$USUARIO" -- git -C "$PASTA" pull --ff-only -q
else
  git clone -q "$REPO" "$PASTA"
fi
mkdir -p "$PASTA/dados"
chown -R "$USUARIO:$USUARIO" "$PASTA"

echo "==> 4/7 Senha do painel..."
CFG="$PASTA/config.json"
SENHA=$(runuser -u "$USUARIO" -- python3 - "$CFG" "${SENHA:-}" <<'PY'
import json, os, secrets, sys
arq, pedida = sys.argv[1], sys.argv[2]
cfg = json.load(open(arq, encoding="utf-8")) if os.path.exists(arq) else {}
painel = cfg.setdefault("painel", {})
painel["senha"] = pedida or painel.get("senha") or secrets.token_urlsafe(9)
painel["celular"] = False      # só o Caddy (HTTPS) fala com o painel
painel.setdefault("porta", 8000)
json.dump(cfg, open(arq, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(painel["senha"])
PY
)
chmod 600 "$CFG"

echo "==> 5/7 Ligando a agência como serviço (liga sozinha com o servidor e reinicia se cair)..."
cat > /etc/systemd/system/agencia.service <<EOF
[Unit]
Description=Agencia de Trade (simulador)
After=network-online.target
Wants=network-online.target

[Service]
User=$USUARIO
WorkingDirectory=$PASTA
Environment=PYTHONIOENCODING=utf-8
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 -u rodar.py simular --sem-navegador
Restart=always
RestartSec=15

[Install]
WantedBy=multi-user.target
EOF
cat > /usr/local/bin/agencia-atualizar <<EOF
#!/usr/bin/env bash
# Baixa a versão nova do GitHub; só reinicia a agência se mudou alguma coisa (os dados ficam).
set -e
ANTES=\$(runuser -u $USUARIO -- git -C $PASTA rev-parse HEAD)
runuser -u $USUARIO -- git -C $PASTA pull --ff-only -q || { echo "não consegui atualizar"; exit 0; }
if [ "\$ANTES" != "\$(runuser -u $USUARIO -- git -C $PASTA rev-parse HEAD)" ]; then
  systemctl restart agencia && echo "atualizou e reiniciou a agência"
else
  echo "já estava na versão mais nova"
fi
EOF
chmod +x /usr/local/bin/agencia-atualizar
cat > /etc/systemd/system/agencia-atualizar.service <<EOF
[Unit]
Description=Atualiza a Agencia de Trade pelo GitHub

[Service]
Type=oneshot
ExecStart=/usr/local/bin/agencia-atualizar
EOF
cat > /etc/systemd/system/agencia-atualizar.timer <<EOF
[Unit]
Description=Atualizacao diaria da Agencia de Trade

[Timer]
OnCalendar=*-*-* 06:17:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

echo "==> 6/7 Endereço com HTTPS..."
IP=$(curl -fsS --max-time 10 https://api.ipify.org || curl -fsS --max-time 10 https://ifconfig.me || hostname -I | awk '{print $1}')
DOMINIO="${DOMINIO:-$(echo "$IP" | tr . -).sslip.io}"
cat > /etc/caddy/Caddyfile <<EOF
$DOMINIO {
    encode gzip
    reverse_proxy 127.0.0.1:8000
}
EOF
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
fi
if iptables -S INPUT 2>/dev/null | grep -q -- "-j REJECT"; then   # imagens da Oracle Cloud vêm bloqueando tudo
  iptables -C INPUT -p tcp --dport 80 -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -p tcp --dport 80 -j ACCEPT
  iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -p tcp --dport 443 -j ACCEPT
  command -v netfilter-persistent >/dev/null 2>&1 && netfilter-persistent save >/dev/null 2>&1 || true
fi

echo "==> 7/7 Ligando tudo..."
systemctl daemon-reload
systemctl enable --now agencia.service agencia-atualizar.timer caddy >/dev/null 2>&1
systemctl restart agencia.service
systemctl reload caddy || systemctl restart caddy

cat <<EOF

=====================================================================
 ✅ Pronto! A Agência de Trade está rodando 24h neste servidor.

   Endereço:  https://$DOMINIO
   Usuário:   agencia
   Senha:     $SENHA        (guarde! fica em $CFG)

 Na 1ª vez a escola baixa o histórico e faz as provas: o endereço só
 abre depois disso (uns 15 a 30 minutos). Pra acompanhar:
   journalctl -u agencia -f        (Ctrl+C pra sair)

 Atualiza sozinha todo dia. Pra atualizar agora:  agencia-atualizar
=====================================================================
EOF
