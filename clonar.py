#!/usr/bin/env python3
"""
CLONADOR DE PÁGINAS — passo 2 de 2: RECONSTRUÇÃO

Uso:  ./clonar.py ~/Downloads/captura-exemplo-com.json [nome-do-clone]

Lê o JSON gerado por capturar.js e monta um clone local autocontido:
grava os assets, reescreve HTML e CSS para caminhos locais, neutraliza
rastreadores e audita o resultado.
"""
import argparse, base64, hashlib, io, json, os, re, sys
from urllib.parse import urlsplit, unquote

RAIZ = os.path.dirname(os.path.abspath(__file__))

# Scripts que NÃO devem rodar no clone (rastreamento / lixo de extensão).
TRACKER_SRC = [
    "chrome-extension://", "moz-extension://", "googletagmanager", "google-analytics",
    "analytics.google", "doubleclick", "clarity", "posthog", "cloudflareinsights",
    "cdn-cgi", "convertexperiments", "facebook.net", "connect.facebook", "hotjar",
    "segment.io", "segment.com", "mixpanel", "amplitude", "intercom", "tiktok",
    "bat.bing.com", "criteo", "taboola", "outbrain", "newrelic", "sentry.io",
    "datadoghq", "optimizely", "vwo.com", "web-vitals", "dead-clicks", "surveys.js",
    # analytics atrás de proxy reverso em domínio próprio (driblam adblock):
    # o domínio é do cliente, então só o nome do arquivo entrega.
    "/static/array.js", "/static/surveys.js", "/static/dead-clicks",
    "/static/recorder", "/i/v0/e/", "/e/?ip=", "gtm.js", "gtag/js",
]
TRACKER_INLINE = [
    "dataLayer", "gtag(", "posthog.init", "__CF$cv", "_conv_q", "window.convert",
    "GTM-", "clarity", "fbq(", "ttq.", "_hjSettings", "analytics.load",
    "mixpanel.init", "amplitude.getInstance", "Sentry.init", "newrelic",
]

MIME_EXT = {
    "text/css": ".css", "application/javascript": ".js", "text/javascript": ".js",
    "image/webp": ".webp", "image/png": ".png", "image/jpeg": ".jpg",
    "image/svg+xml": ".svg", "image/gif": ".gif", "image/avif": ".avif",
    "video/webm": ".webm", "video/mp4": ".mp4", "font/woff2": ".woff2",
    "font/woff": ".woff", "application/json": ".json",
}


def eh_tracker(url):
    return any(t in url for t in TRACKER_SRC)


def nome_local(url, meta, usados):
    """Nome de arquivo estável e sem colisão para uma URL."""
    sp = urlsplit(url)
    base = unquote(os.path.basename(sp.path)) or "index"
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)[:80]
    if not os.path.splitext(base)[1]:
        base += MIME_EXT.get((meta.get("type") or "").split(";")[0], "")
    if base in usados and usados[base] != url:
        base = hashlib.md5(url.encode()).hexdigest()[:6] + "_" + base
    usados[base] = url
    return base


def variantes(url):
    """Todas as formas em que essa URL pode aparecer no HTML."""
    sp = urlsplit(url)
    q = ("?" + sp.query) if sp.query else ""
    vistos, saida = set(), []
    for v in (url,
              sp.scheme + "://" + sp.netloc + sp.path + q,
              sp.scheme + "://" + sp.netloc + sp.path,
              "//" + sp.netloc + sp.path + q,
              "//" + sp.netloc + sp.path,
              sp.path + q,
              sp.path):
        if v and v not in vistos and len(v) > 1:
            vistos.add(v); saida.append(v)
            esc = v.replace("&", "&amp;")
            if esc != v:
                saida.append(esc)
    return saida


def completar_externos(html, assets, out):
    """Baixa do terminal os assets externos que sobraram no HTML.

    A captura no navegador às vezes perde arquivo de CDN público por CORS.
    Esses domínios costumam responder normalmente fora do navegador, então
    dá para fechar o buraco aqui — inclusive fontes, deixando o clone 100%
    offline.
    """
    import urllib.request
    from urllib.parse import urljoin

    UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

    def baixar(url):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read(), r.headers.get("Content-Type", "")

    usados = {f: None for f in os.listdir(assets)}
    ok = falhou = 0

    for _ in range(2):                      # 2 níveis: CSS → fontes que ele usa
        alvos = set()
        for m in re.finditer(r'(?:src|<link[^>]+href)="(https?://[^"]+)"', html):
            alvos.add(m.group(1))
        for m in re.finditer(r"url\(\s*['\"]?(https?://[^'\")]+)", html):
            alvos.add(m.group(1))
        if not alvos:
            break
        novos = False
        for url in sorted(alvos):
            if eh_tracker(url):
                continue
            try:
                dados, ctype = baixar(url)
            except Exception as e:
                print("   nao baixou: %s (%s)" % (url.split("/")[-1][:40], str(e)[:30]))
                falhou += 1
                continue
            base = nome_local(url, {"type": ctype}, usados)
            open(os.path.join(assets, base), "wb").write(dados)
            # se for CSS, puxa também o que ele referencia (fontes)
            if base.endswith(".css") or "css" in ctype:
                txt = dados.decode("utf-8", "replace")
                for m in re.finditer(r"url\(\s*['\"]?(?!data:)([^'\")]+)", txt):
                    filho = urljoin(url, m.group(1))
                    try:
                        d2, c2 = baixar(filho)
                    except Exception:
                        continue
                    b2 = nome_local(filho, {"type": c2}, usados)
                    open(os.path.join(assets, b2), "wb").write(d2)
                    txt = txt.replace(m.group(1), b2)
                open(os.path.join(assets, base), "w", encoding="utf-8").write(txt)
            tok = "\x00EXT%d\x00" % ok
            for v in variantes(url):
                if v in html:
                    html = html.replace(v, tok)
            html = html.replace(tok, "assets/" + base)
            ok += 1
            novos = True
        if not novos:
            break

    # CSS locais podem apontar para fora (@import de fontes, por exemplo).
    # Sem isto o clone continua dependendo do Google Fonts para renderizar.
    for _ in range(2):
        mudou = False
        for arq in sorted(os.listdir(assets)):
            if not arq.endswith(".css"):
                continue
            cp = os.path.join(assets, arq)
            txt = io.open(cp, encoding="utf-8", errors="replace").read()
            # url(...) já cobre "@import url(...)". O padrão separado de @import
            # é só para a forma sem url(), e NÃO pode parar no ";" — a query do
            # Google Fonts tem ";" dentro (wght@0,100..900;1,100..900).
            achados = set(re.findall(r"url\(\s*['\"]?(https?://[^'\")]+)", txt))
            achados |= set(re.findall(r"@import\s+['\"](https?://[^'\"]+)['\"]", txt))
            # maiores primeiro: evita que um prefixo corrompa a URL completa
            for url in sorted(achados, key=len, reverse=True):
                if eh_tracker(url):
                    continue
                try:
                    dados, ctype = baixar(url)
                except Exception:
                    falhou += 1
                    continue
                base = nome_local(url, {"type": ctype}, usados)
                open(os.path.join(assets, base), "wb").write(dados)
                txt = txt.replace(url, base)
                ok += 1
                mudou = True
            io.open(cp, "w", encoding="utf-8", errors="replace").write(txt)
        if not mudou:
            break

    if ok or falhou:
        print("completados do terminal: %d  (falharam: %d)" % (ok, falhou))
    return html


def main():
    ap = argparse.ArgumentParser(description="Reconstrói um clone a partir da captura JSON")
    ap.add_argument("json", help="arquivo gerado por capturar.js")
    ap.add_argument("nome", nargs="?", help="nome da pasta do clone (padrão: host da página)")
    ap.add_argument("--manter-trackers", action="store_true",
                    help="não neutraliza os scripts de rastreamento")
    ap.add_argument("--offline", action="store_true",
                    help="não tenta baixar do terminal os assets externos que sobraram")
    ap.add_argument("--bloquear", default="",
                    help="trechos de URL extras a neutralizar, separados por vírgula "
                         "(para analytics em domínio próprio)")
    a = ap.parse_args()

    if a.bloquear:
        TRACKER_SRC.extend(x.strip() for x in a.bloquear.split(",") if x.strip())

    if not os.path.exists(a.json):
        sys.exit("ERRO: %s não encontrado" % a.json)
    d = json.load(open(a.json))
    page_url, files = d["pageUrl"], d["files"]
    html = d["html"]

    nome = a.nome or re.sub(r"[^a-z0-9]+", "-", urlsplit(page_url).hostname.lower()).strip("-")
    out = os.path.join(RAIZ, "clones", nome)
    assets = os.path.join(out, "assets")
    os.makedirs(assets, exist_ok=True)

    print("origem : %s" % page_url)
    print("titulo : %s" % d.get("title", "?"))
    print("captura: %s | %d arquivos" % (d.get("capturedAt", "?"), len(files)))
    print("destino: %s\n" % out)

    # ── 1. grava os assets ────────────────────────────────────────
    usados, url2local, css_orig = {}, {}, {}
    gravados = ignorados = 0
    for url, meta in files.items():
        if eh_tracker(url):
            ignorados += 1
            continue
        base = nome_local(url, meta, usados)
        with open(os.path.join(assets, base), "wb") as f:
            f.write(base64.b64decode(meta["b64"]))
        url2local[url] = "assets/" + base
        if base.endswith(".css"):
            css_orig[base] = url
        gravados += 1
    print("assets gravados: %d  (trackers ignorados: %d)" % (gravados, ignorados))

    # ── 2. reescreve o HTML ───────────────────────────────────────
    # Substitui via token: trocar direto pelo caminho local faz a variante
    # curta ("/x.js") casar DENTRO do que já foi trocado ("assets/x.js"),
    # produzindo "assetsassets/x.js".
    n, tokens = 0, {}
    for idx, (url, local) in enumerate(sorted(url2local.items(), key=lambda kv: -len(kv[0]))):
        tok = "\x00CLONE%d\x00" % idx
        achou = False
        for v in variantes(url):
            if v in html:
                html = html.replace(v, tok); n += 1; achou = True
        if achou:
            tokens[tok] = local
    for tok, local in tokens.items():
        html = html.replace(tok, local)
    # âncoras que apontam para a própria página
    base_page = page_url.split("#")[0]
    html, k = re.subn(re.escape(base_page) + r"#", "#", html)
    n += k
    print("URLs reescritas no HTML: %d" % n)

    # ── 3. neutraliza rastreadores ────────────────────────────────
    mortos = []
    if not a.manter_trackers:
        def mata(m):
            attrs, corpo = m.group(1), m.group(2)
            if "data-clone-disabled" in attrs:
                return m.group(0)
            src = re.search(r'src="([^"]*)"', attrs)
            porque = None
            if src:
                for t in TRACKER_SRC:
                    if t in src.group(1): porque = t; break
            else:
                for t in TRACKER_INLINE:
                    if t in corpo: porque = t; break
            if not porque:
                return m.group(0)
            mortos.append(porque)
            return ('<script type="text/plain" data-clone-disabled="%s"%s>%s</script>'
                    % (porque, attrs, corpo))

        html = re.sub(r"<script\b([^>]*)>(.*?)</script>", mata, html, flags=re.S)
        html, n_ifr = re.subn(
            r'<iframe([^>]*)src="(?:[^"]*saved_resource[^"]*|https?://[^"]*(?:%s)[^"]*)"([^>]*)>'
            % "|".join(map(re.escape, ["googletagmanager", "cdn-cgi", "doubleclick", "facebook"])),
            r'<iframe\1data-clone-disabled="tracker-iframe"\2>', html)
        html, n_ns = re.subn(r"<noscript><iframe[^>]*(?:googletagmanager|facebook)[^>]*>.*?</noscript>",
                             "<!-- tracker noscript removido -->", html, flags=re.S)
        print("scripts neutralizados: %d | iframes: %d | noscript: %d"
              % (len(mortos), n_ifr, n_ns))

    io.open(os.path.join(out, "index.html"), "w",
            encoding="utf-8", errors="surrogatepass").write(html)

    # ── 4. reescreve url() dentro dos CSS ─────────────────────────
    n_css = 0
    base_por_url = {u: os.path.basename(l) for u, l in url2local.items()}
    for arq, orig in css_orig.items():
        p = os.path.join(assets, arq)
        c = io.open(p, encoding="utf-8", errors="replace").read()

        def fix(m):
            nonlocal n_css
            bruto = m.group(1).strip("'\" ")
            if bruto.startswith("data:"):
                return m.group(0)
            try:
                from urllib.parse import urljoin
                alvo = urljoin(orig, bruto)
            except Exception:
                return m.group(0)
            if alvo in base_por_url:
                n_css += 1
                return "url(%s)" % base_por_url[alvo]
            fim = os.path.basename(alvo.split("?")[0])
            for u, b in base_por_url.items():
                if u.split("?")[0].endswith("/" + fim):
                    n_css += 1
                    return "url(%s)" % b
            return m.group(0)

        c = re.sub(r"url\(([^)]+)\)", fix, c)
        io.open(p, "w", encoding="utf-8", errors="replace").write(c)
    print("url() de CSS reescritos: %d" % n_css)

    # ── 4b. completa o que faltou, baixando do terminal ───────────
    if not a.offline:
        html = completar_externos(html, assets, out)
        io.open(os.path.join(out, "index.html"), "w",
                encoding="utf-8", errors="surrogatepass").write(html)

    # ── 5. auditoria ──────────────────────────────────────────────
    vivo = re.sub(r"<script\b[^>]*data-clone-disabled.*?</script>", "", html, flags=re.S)

    # assets = o que o navegador busca sozinho (src, e href de <link>)
    assets_ref = set(m.group(1) for m in re.finditer(
        r'src="(?!https?:|//|data:|chrome-extension)([^"]+)"', vivo))
    assets_ref |= set(m.group(1) for m in re.finditer(
        r'<link[^>]+href="(?!https?:|//|data:)([^"]+)"', vivo))
    faltando = sorted(r for r in assets_ref if not os.path.exists(
        os.path.join(out, unquote(r.split("?")[0]))))

    # links de navegação: só disparam se alguém clicar
    links_ext = sorted(set(m.group(1) for m in re.finditer(
        r'<a [^>]*href="(https?://[^"]+)"', vivo)))

    # externos que o navegador busca SOZINHO ao abrir a página
    auto_ext = set()
    for m in re.finditer(r'(?:src|<link[^>]+href)="(https?://[^"]+)"', vivo):
        auto_ext.add(urlsplit(m.group(1)).netloc)
    for m in re.finditer(r"url\(\s*['\"]?(https?://[^'\")]+)", vivo):
        auto_ext.add(urlsplit(m.group(1)).netloc)
    auto_ext.discard("www.w3.org")

    print("\n=== AUDITORIA ===")
    print("assets referenciados: %d | faltando: %d" % (len(assets_ref), len(faltando)))
    for f in faltando:
        print("   FALTA:", f)
    if auto_ext:
        print("\n!! %d domínio(s) que a página ainda chama SOZINHA ao abrir:"
              % len(auto_ext))
        for dom in sorted(auto_ext):
            print("     -", dom)
        print("   Se for analytics em domínio próprio, rode de novo com:")
        print("     --bloquear %s" % ",".join(sorted(auto_ext)))
    else:
        print("chamadas externas automáticas: nenhuma  [OK]")
    if links_ext:
        print("\n%d link(s) de navegação apontam para fora (só ao clicar):" % len(links_ext))
        for l in links_ext[:5]:
            print("     -", l)
        if len(links_ext) > 5:
            print("     ... e mais %d" % (len(links_ext) - 5))

    tot = sum(os.path.getsize(os.path.join(assets, f)) for f in os.listdir(assets))
    print("\ntamanho: %.1f MB em %d arquivos" % (tot / 1048576, len(os.listdir(assets))))
    print("\nservir com:  ./servir.py %s" % nome)


if __name__ == "__main__":
    main()
