#!/usr/bin/env bash
# echopage — envia a pasta local para a VPS e sobe o serviço.
#   ./deploy/enviar.sh root@108.174.151.220 22022
#
# Manda o código como ele está na sua máquina (inclusive o que ainda não foi
# commitado), roda o instalador lá e reinicia o serviço. Os clones e capturas
# que já existem na VPS não são tocados.
set -euo pipefail

ALVO="${1:-}"; PORTA="${2:-22}"
[ -n "$ALVO" ] || { echo "uso: $0 usuario@ip [porta_ssh]"; exit 1; }
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SSH=(ssh -p "$PORTA" -o StrictHostKeyChecking=accept-new)

echo "── 1. enviando o código ──"
rsync -az --delete --info=stats1 -e "ssh -p $PORTA -o StrictHostKeyChecking=accept-new" \
  --exclude 'clones/' --exclude '.capturas/' --exclude '.zips/' \
  --exclude '__pycache__/' --exclude '.git/' --exclude '*.pyc' \
  "$RAIZ"/ "$ALVO":/opt/echopage/

echo "── 2. instalando e subindo ──"
"${SSH[@]}" "$ALVO" 'bash /opt/echopage/deploy/instalar.sh'

# o instalador faz enable --now, que não reinicia um serviço já de pé: sem
# isto o painel.py novo só entrava em vigor no próximo boot
echo "── 3. reiniciando ──"
"${SSH[@]}" "$ALVO" 'systemctl restart echopage && systemctl is-active echopage'
