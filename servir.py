#!/usr/bin/env python3
"""Serve um clone em localhost com os MIME types corretos.

Uso:  ./servir.py <nome-do-clone> [porta]
      ./servir.py            (lista os clones disponíveis)
"""
import http.server, socketserver, mimetypes, os, sys, webbrowser

RAIZ = os.path.dirname(os.path.abspath(__file__))
CLONES = os.path.join(RAIZ, "clones")

for ext, tipo in {".webp": "image/webp", ".webm": "video/webm", ".avif": "image/avif",
                  ".svg": "image/svg+xml", ".woff2": "font/woff2", ".woff": "font/woff",
                  ".mp4": "video/mp4", ".m4v": "video/mp4"}.items():
    mimetypes.add_type(tipo, ext)

disponiveis = sorted(d for d in os.listdir(CLONES)) if os.path.isdir(CLONES) else []
if len(sys.argv) < 2:
    print("clones disponíveis:")
    for d in disponiveis:
        print("   ", d)
    print("\nuso: ./servir.py <nome> [porta]")
    sys.exit(0)

nome = sys.argv[1]
porta = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
alvo = os.path.join(CLONES, nome)
if not os.path.isdir(alvo):
    sys.exit("ERRO: clone '%s' não existe. Disponíveis: %s" % (nome, ", ".join(disponiveis) or "nenhum"))

os.chdir(alvo)
socketserver.TCPServer.allow_reuse_address = True
url = "http://localhost:%d/" % porta
with socketserver.TCPServer(("127.0.0.1", porta), http.server.SimpleHTTPRequestHandler) as s:
    print("servindo '%s' em %s   (Ctrl+C para parar)" % (nome, url), flush=True)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    s.serve_forever()
