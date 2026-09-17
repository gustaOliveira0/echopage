#!/usr/bin/env bash
# echopage — põe o painel no ar pela porta 80, protegido por senha.
#   sudo bash deploy/publicar.sh <usuario> [senha]
#
# Sem domínio: o painel abre em http://<ip>/ e o Basic Auth do nginx é o que
# separa você de quem mais achar a porta. Sem isso, qualquer um manda a sua
# VPS baixar qualquer site da internet.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "rode com sudo"; exit 1; }

USUARIO="${1:-echopage}"
SENHA="${2:-$(head -c 18 /dev/urandom | base64 | tr -d '/+=' | head -c 20)}"

command -v nginx >/dev/null 2>&1 || {
  apt-get update -qq
  apt-get install -y --no-install-recommends nginx apache2-utils >/dev/null
}
command -v htpasswd >/dev/null 2>&1 || apt-get install -y apache2-utils >/dev/null

htpasswd -bc /etc/nginx/echopage.htpasswd "$USUARIO" "$SENHA" >/dev/null 2>&1
chmod 640 /etc/nginx/echopage.htpasswd
chown root:www-data /etc/nginx/echopage.htpasswd

install -m 644 /opt/echopage/deploy/nginx-echopage-ip.conf \
        /etc/nginx/sites-available/echopage
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/echopage /etc/nginx/sites-enabled/echopage
nginx -t
systemctl enable --now nginx
systemctl reload nginx

echo
echo "════════════════════════════════════════════════════════"
echo "  painel:  http://$(curl -fsS --max-time 5 ifconfig.me || hostname -I | awk '{print $1}')/"
echo "  usuário: $USUARIO"
echo "  senha:   $SENHA"
echo "════════════════════════════════════════════════════════"
