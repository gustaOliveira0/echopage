#!/usr/bin/env bash
# echopage — instalação na VPS (Ubuntu/Debian).
#   sudo bash deploy/instalar.sh
set -euo pipefail

USUARIO="${SUDO_USER:-$USER}"
DESTINO="/opt/echopage"
[ "$(id -u)" -eq 0 ] || { echo "rode com sudo"; exit 1; }

echo "── 1. dependências ──"
apt-get update -qq
apt-get install -y --no-install-recommends \
  python3 git curl ca-certificates xvfb fonts-liberation fonts-noto-color-emoji \
  libnss3 libatk-bridge2.0-0 libgtk-3-0 libgbm1 libasound2 libxshmfence1 >/dev/null

echo "── 2. Google Chrome ──"
if ! command -v google-chrome >/dev/null 2>&1; then
  curl -fsSL -o /tmp/chrome.deb \
    https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
  apt-get install -y /tmp/chrome.deb >/dev/null
  rm -f /tmp/chrome.deb
fi
google-chrome --version

echo "── 3. código ──"
# O deploy/enviar.sh já deixou a pasta aqui por rsync — inclusive o que ainda
# não foi commitado. Só busca no GitHub quem não tem código nenhum.
if [ -f "$DESTINO/painel.py" ] && [ ! -d "$DESTINO/.git" ]; then
  echo "código já enviado por rsync"
elif [ -d "$DESTINO/.git" ]; then
  git -C "$DESTINO" pull --ff-only
else
  git clone --depth 1 https://github.com/gustaOliveira0/echopage.git "$DESTINO"
fi
mkdir -p "$DESTINO"/{clones,.capturas,.zips}
id -u echopage >/dev/null 2>&1 || useradd -r -m -d /var/lib/echopage -s /usr/sbin/nologin echopage
chown -R echopage:echopage "$DESTINO" /var/lib/echopage

echo "── 3b. swap ──"
# 2 GB de RAM não seguram o Chrome numa landing pesada; sem swap o kernel
# mata a captura no meio. 4 GB de arquivo custam disco, e disco tem 50 GB.
if [ ! -f /swapfile ] && [ "$(free -m | awk '/^Swap:/{print $2}')" -lt 1024 ]; then
  fallocate -l 4G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=4096 status=none
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
free -h | awk '/^Swap:/{print "swap: "$2}'

echo "── 4. token ──"
CONF=/etc/echopage.env
if [ ! -f "$CONF" ]; then
  TOKEN=$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 40)
  cat > "$CONF" <<EOF
# Token que o frontend precisa mandar em Authorization: Bearer <token>
ECHOPAGE_TOKEN=$TOKEN
# Origens liberadas para CORS, separadas por vírgula (o domínio da Vercel)
ECHOPAGE_ORIGENS=
# Escuta só em localhost; quem expõe é o nginx, com TLS
ECHOPAGE_HOST=127.0.0.1
EOF
  chmod 600 "$CONF"; chown echopage:echopage "$CONF"
fi

echo "── 5. serviço ──"
install -m 644 "$DESTINO/deploy/echopage.service" /etc/systemd/system/echopage.service
systemctl daemon-reload
systemctl enable --now echopage
sleep 2
systemctl --no-pager --lines=5 status echopage || true

echo
echo "════════════════════════════════════════════════════════"
echo "  TOKEN:  $(grep ECHOPAGE_TOKEN "$CONF" | cut -d= -f2)"
echo
echo "  Falta: 1) pôr o domínio da Vercel em ECHOPAGE_ORIGENS"
echo "            no $CONF e rodar: systemctl restart echopage"
echo "         2) configurar o nginx — veja deploy/nginx-echopage.conf"
echo "════════════════════════════════════════════════════════"
