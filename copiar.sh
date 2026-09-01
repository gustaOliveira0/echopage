#!/bin/bash
# Coloca capturar.js na área de transferência (ou abre para você copiar).
cd "$(dirname "$0")"
F="$PWD/capturar.js"
for c in wl-copy xsel xclip; do
  if command -v $c >/dev/null 2>&1; then
    case $c in
      wl-copy) wl-copy               < "$F" ;;
      xsel)    xsel -ib              < "$F" ;;
      xclip)   xclip -selection clip < "$F" ;;
    esac
    echo "copiado para a área de transferência ($c)"
    echo "agora: F12 na página-alvo → Console → Ctrl+V → Enter"
    exit 0
  fi
done
echo "sem ferramenta de clipboard instalada — abrindo no navegador."
echo "faça Ctrl+A, Ctrl+C, e cole no Console (F12) da página-alvo."
(xdg-open "file://$F" >/dev/null 2>&1 || google-chrome "file://$F" >/dev/null 2>&1) &
