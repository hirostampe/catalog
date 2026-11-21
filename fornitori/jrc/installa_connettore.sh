#!/usr/bin/env bash
# Installa il connettore Claude del bot James Ross sul server (Debian/Ubuntu).
# Uso:  cd /opt/hirostampe/fornitori/jrc && bash installa_connettore.sh
set -euo pipefail
cd "$(dirname "$0")"
DIR="$(pwd)"

echo "== 1/5 Librerie"
.venv/bin/pip install -q -r requirements.txt

echo "== 2/5 Indirizzo segreto"
touch .env && chmod 600 .env
if ! grep -q '^JRC_MCP_SEGRETO=.\{20,\}' .env; then
  sed -i '/^JRC_MCP_SEGRETO=/d' .env
  echo "JRC_MCP_SEGRETO=$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')" >> .env
fi
SEGRETO=$(grep '^JRC_MCP_SEGRETO=' .env | cut -d= -f2)

IP=$(curl -4 -s --max-time 10 https://api.ipify.org || hostname -I | awk '{print $1}')
DOMINIO="${IP//./-}.sslip.io"

echo "== 3/5 Servizio del connettore"
cat > /etc/systemd/system/hirostampe-jrc.service <<EOF
[Unit]
Description=Connettore Claude - James Ross (Hirostampe)
After=network-online.target

[Service]
WorkingDirectory=$DIR
ExecStart=$DIR/.venv/bin/python $DIR/mcp_server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now hirostampe-jrc >/dev/null
systemctl restart hirostampe-jrc

echo "== 4/5 HTTPS (Caddy)"
if ! command -v caddy >/dev/null; then
  OCCUPATE=$(ss -ltnp | grep -E ':(80|443)\s' || true)
  if [ -n "$OCCUPATE" ]; then
    echo "ATTENZIONE: le porte 80/443 sono già usate da un altro programma:"
    echo "$OCCUPATE"
    echo "Fermati qui e manda uno screenshot a Claude."
    exit 1
  fi
  apt-get update -qq && apt-get install -y -qq caddy
fi
BLOCCO="$DOMINIO {
	reverse_proxy 127.0.0.1:8765
}"
if [ ! -s /etc/caddy/Caddyfile ] || grep -q "Caddy's configuration file" /etc/caddy/Caddyfile; then
  echo "$BLOCCO" > /etc/caddy/Caddyfile
elif ! grep -q "$DOMINIO" /etc/caddy/Caddyfile; then
  printf '\n%s\n' "$BLOCCO" >> /etc/caddy/Caddyfile
fi
systemctl enable caddy >/dev/null
systemctl reload caddy 2>/dev/null || systemctl restart caddy

echo "== 5/5 Verifica (può servire fino a 1 minuto per il certificato)"
URL="https://$DOMINIO/$SEGRETO/mcp"
OK=""
for i in $(seq 1 12); do
  CODICE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -X POST "$URL" \
    -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' || true)
  if [ "$CODICE" = "200" ]; then OK=1; break; fi
  sleep 5
done

echo
if [ -n "$OK" ]; then
  echo "TUTTO OK. Indirizzo del connettore (copialo, è come una password):"
  echo
  echo "   $URL"
  echo
else
  echo "Il connettore è acceso ma non risponde da internet (codice: $CODICE)."
  echo "Probabile firewall Hetzner: apri le porte 80 e 443. Poi rilancia questo script."
  echo "Indirizzo previsto: $URL"
fi
