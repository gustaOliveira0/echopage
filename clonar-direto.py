#!/usr/bin/env python3
"""
CLONADOR DE PÁGINAS — caminho direto (sem navegador)

    ./clonar-direto.py https://exemplo.com/pagina [nome-do-clone]

Baixa a página e todos os assets pelo terminal e monta o clone, sem precisar
colar nada no console. Só funciona se o terminal tiver o mesmo acesso que o
navegador — ou seja, com **VPN no sistema inteiro**. Se a VPN for extensão do
Chrome, use o caminho do navegador (capturar.js), porque aqui vai dar 403.

Limite importante: isto baixa o HTML **cru do servidor**, antes do JavaScript
rodar. Para páginas estáticas (landing pages) o resultado é igual ao do
navegador. Para páginas que montam conteúdo via JS, use capturar.js.
"""
import argparse, base64, os, re, sys
from urllib.parse import urljoin, urlsplit
import urllib.request, urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# reaproveita a lógica já testada
from clonar import reconstruir, eh_tracker, baixar_url as baixar


def urls_do_html(html, base):
    achados = set()
    for m in re.finditer(r'(?:src|href|data-src|data-lazy-src)="([^"]+)"', html):
        achados.add(m.group(1))
    for m in re.finditer(r'(?:srcset|data-srcset)="([^"]+)"', html):
        for parte in m.group(1).split(","):
            achados.add(parte.strip().split()[0] if parte.strip() else "")
    for m in re.finditer(r"url\(\s*['\"]?(?!data:)([^'\")]+)", html):
        achados.add(m.group(1))
    saida = set()
    for u in achados:
        u = u.strip()
        if not u or u.startswith(("#", "data:", "javascript:", "mailto:", "tel:")):
            continue
        try:
            full = urljoin(base, u)
        except Exception:
            continue
        if full.startswith(("http://", "https://")):
            saida.add(full.split("#")[0])
    return saida


def main():
    ap = argparse.ArgumentParser(description="Clona uma página direto pelo terminal")
    ap.add_argument("url")
    ap.add_argument("nome", nargs="?")
    ap.add_argument("--manter-trackers", action="store_true")
    ap.add_argument("--bloquear", default="")
    a = ap.parse_args()

    print("baixando página: %s" % a.url)
    try:
        bruto, ctype = baixar(a.url)
    except urllib.error.HTTPError as e:
        print("\nHTTP %s — o servidor recusou." % e.code)
        if e.code in (403, 503):
            print("Provável Cloudflare/geo-bloqueio: o terminal não está saindo pela VPN.")
            print("Confira com:  curl -s https://ipinfo.io/json | head")
            print("Se o IP não for do país esperado, use o caminho do navegador:")
            print("  ./copiar.sh   →  cole capturar.js no Console da página")
        sys.exit(1)
    except Exception as e:
        sys.exit("falhou: %s" % e)

    html = bruto.decode("utf-8", "replace")
    print("HTML: %.0f KB" % (len(bruto) / 1024))

    # 1ª onda: o que o HTML referencia
    fila = urls_do_html(html, a.url)
    print("assets no HTML: %d" % len(fila))

    files, vistos = {}, set()
    ok = falhou = 0
    for onda in range(3):                    # HTML → CSS → fontes do CSS
        proxima = set()
        for url in sorted(fila):
            if url in vistos or eh_tracker(url):
                continue
            vistos.add(url)
            try:
                dados, ct = baixar(url, referer=a.url)
            except Exception:
                falhou += 1
                continue
            files[url] = {"b64": base64.b64encode(dados).decode(),
                          "type": ct.split(";")[0], "size": len(dados)}
            ok += 1
            if "css" in ct or url.split("?")[0].endswith(".css"):
                txt = dados.decode("utf-8", "replace")
                for m in re.finditer(r"url\(\s*['\"]?(?!data:)([^'\")]+)", txt):
                    proxima.add(urljoin(url, m.group(1)))
                for m in re.finditer(r"@import\s+['\"]([^'\"]+)['\"]", txt):
                    proxima.add(urljoin(url, m.group(1)))
        print("  onda %d: %d baixados, %d falhas" % (onda + 1, ok, falhou))
        if not proxima:
            break
        fila = proxima

    d = {"pageUrl": a.url, "title": "", "capturedAt": "",
         "html": html, "files": files, "log": []}
    print()
    reconstruir(d, a.nome, manter_trackers=a.manter_trackers, bloquear=a.bloquear)


if __name__ == "__main__":
    main()
