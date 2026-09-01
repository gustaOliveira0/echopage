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

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")


def baixar_url(url, referer=None, timeout=25):
    """Baixa uma URL e descomprime a resposta.

    Servidores mandam gzip mesmo sem pedirmos; sem descomprimir, o HTML
    vira bytes binários e a varredura de assets não acha nada.
    """
    import gzip, zlib, urllib.request
    h = {"User-Agent": UA, "Accept": "*/*",
         "Accept-Language": "en-US,en;q=0.9",
         "Accept-Encoding": "gzip, deflate"}
    if referer:
        h["Referer"] = referer
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        dados = r.read()
        enc = (r.headers.get("Content-Encoding") or "").lower()
        if enc == "gzip":
            dados = gzip.decompress(dados)
        elif enc == "deflate":
            try:
                dados = zlib.decompress(dados)
            except zlib.error:
                dados = zlib.decompress(dados, -zlib.MAX_WBITS)
        return dados, r.headers.get("Content-Type", "")

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
    "convert_tracking", "checktrafficnew", "/ajax.php/extensions",
    "facebook.com/tr", "/pagead/viewthroughconversion", "/signals/config",
    # redes de tracking de afiliado/CPA e verificação de tráfego (cloaking)
    "mxj5trk", "trackjs", "/track.js", "voluum", "redtrack", "binom",
    "clickmagick", "everflow", "cloaker",
    # PostHog atrás de proxy próprio: a chave de projeto começa sempre por
    # "phc_" e o SDK carrega de /array/<chave>/ — pega o config.js disfarçado.
    "phc_", "/array/phc",
]
TRACKER_INLINE = [
    "dataLayer", "gtag(", "posthog.init", "__CF$cv", "_conv_q", "window.convert",
    "GTM-", "clarity", "fbq(", "ttq.", "_hjSettings", "analytics.load",
    "mixpanel.init", "amplitude.getInstance", "Sentry.init", "newrelic",
]

# O JavaScript do site chama fbq(), gtag(), posthog.capture()... Se a gente
# apenas remove os rastreadores, essas chamadas viram ReferenceError e podem
# derrubar o resto da página. Os stubs absorvem as chamadas sem fazer nada.
STUBS = """<script data-clone="stubs">
window.dataLayer=window.dataLayer||[];
window.gtag=window.gtag||function(){};
window.ga=window.ga||function(){};
window.fbq=window.fbq||function(){};window._fbq=window.fbq;
window.ttq=window.ttq||{track:function(){},page:function(){},load:function(){},identify:function(){}};
window.clarity=window.clarity||function(){};
window.posthog=window.posthog||{init:function(){},capture:function(){},register:function(){},identify:function(){},onFeatureFlags:function(){},people:{set:function(){}}};
window.analytics=window.analytics||{track:function(){},page:function(){},identify:function(){},load:function(){},ready:function(){}};
window.mixpanel=window.mixpanel||{init:function(){},track:function(){}};
window.amplitude=window.amplitude||{getInstance:function(){return{init:function(){},logEvent:function(){}}}};
window.hj=window.hj||function(){};window._hjSettings=window._hjSettings||{};
window._conv_q=window._conv_q||[];
window.convert=window.convert||{currentData:{experiences:{}}};
window.uetq=window.uetq||[];
window.snaptr=window.snaptr||function(){};
window.obApi=window.obApi||function(){};
window.Sentry=window.Sentry||{init:function(){},captureException:function(){}};
</script>"""


def redirect_snippet(dest):
    """Manda os CTAs e links para o destino, SEM quebrar a UI da página.

    Redireciona cliques em link/botão (e elementos com cursor:pointer, que
    são os CTAs em <div> dessas landers), mas ignora quem estiver dentro de
    um FAQ, accordion, slider, tab ou menu — assim o FAQ continua abrindo e
    o cronômetro/carrossel seguem rodando com o JS original do site. Roda na
    fase de captura para decidir antes dos handlers do próprio site.
    """
    d = dest.replace("\\", "\\\\").replace('"', '\\"')
    return ('<script data-clone="redirect">\n'
            '(function(){var DEST="' + d + '";\n'
            # classes/ids de UI interativa que NÃO devem virar redirect
            'var UI=/faq|accordion|collaps|toggle|question|answer|swiper|splide|'
            'slider|carousel|\\btabs?\\b|dropdown|hamburger|menu|modal|popup|'
            'lightbox|tooltip|counter|countdown|timer/i;\n'
            'function cls(el){if(!el||el.className==null)return "";'
            'var c=el.className;return (c.baseVal!==undefined?c.baseVal:c)+"";}\n'
            'function ui(el){while(el&&el!==document.documentElement){'
            'if(UI.test(cls(el)))return true;'
            'if(el.getAttribute){if(UI.test(el.getAttribute("id")||""))return true;'
            'var r=el.getAttribute("role")||"";if(/tab|menuitem|switch/.test(r))return true;}'
            'el=el.parentElement;}return false;}\n'
            'function clic(el){while(el&&el!==document.documentElement){'
            'var t=el.tagName?el.tagName.toLowerCase():"";'
            'if(t==="a"||t==="button")return true;'
            'if(t==="input"){var y=(el.type||"").toLowerCase();'
            'if(y==="submit"||y==="button"||y==="image")return true;}'
            'if(el.getAttribute&&(el.getAttribute("role")==="button"||el.hasAttribute("onclick")))return true;'
            'try{if(getComputedStyle(el).cursor==="pointer")return true;}catch(_){}'
            'el=el.parentElement;}return false;}\n'
            'function go(e){e.preventDefault();e.stopPropagation();'
            'if(e.stopImmediatePropagation)e.stopImmediatePropagation();'
            'window.location.href=DEST;return false;}\n'
            'document.addEventListener("click",function(e){'
            'if(ui(e.target))return;if(clic(e.target))go(e);},true);\n'
            'document.addEventListener("submit",function(e){'
            'if(!ui(e.target))go(e);},true);\n'
            '})();\n</script>')


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


def trocar(html, alvo, novo):
    """Troca `alvo` por `novo` só quando ele é um valor INTEIRO.

    Substring solta é perigosa: a variante curta de uma URL ("/default")
    casa dentro de um caminho já resolvido ("assets/x_index"), produzindo
    "assets/x_indexassets/y_default". Exigir delimitador dos dois lados
    (aspas, parênteses, vírgula, espaço) elimina isso — e ainda cobre
    srcset, que é uma lista separada por vírgula.
    """
    padrao = r'(?<=["\'(,\s])' + re.escape(alvo) + r'(?=["\')\s,])'
    return re.subn(padrao, novo.replace("\\", "\\\\"), html)


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
    from urllib.parse import urljoin

    baixar = baixar_url

    usados = {f: None for f in os.listdir(assets)}
    pendentes = {}
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
            # Só as formas absolutas: aqui a URL sempre aparece completa no
            # HTML, e a variante curta ("/default") casaria dentro de um
            # caminho já resolvido, gerando "assets/xassets/y".
            tok = "\x00EXT%d\x00" % ok
            sp_u = urlsplit(url)
            q_u = ("?" + sp_u.query) if sp_u.query else ""
            for v in (url,
                      sp_u.scheme + "://" + sp_u.netloc + sp_u.path + q_u,
                      sp_u.scheme + "://" + sp_u.netloc + sp_u.path,
                      "//" + sp_u.netloc + sp_u.path + q_u,
                      "//" + sp_u.netloc + sp_u.path):
                html, _k = trocar(html, v, tok)
            pendentes[tok] = "assets/" + base
            ok += 1
            novos = True
        if not novos:
            break

    for tok, local in pendentes.items():
        html = html.replace(tok, local)

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


def podar_css(assets):
    """Remove de @font-face/background as url() que não existem localmente.

    Sem isto o navegador pede arquivos 404 a cada carregamento — barulho no
    console e requisição desperdiçada. Só poda quando sobra alternativa
    válida na mesma declaração: se TODAS quebraram, mantém como está, porque
    aí o problema é da origem e apagar não conserta nada.
    """
    from urllib.parse import unquote
    podadas = intactas = 0

    def existe(u):
        limpo = unquote(u.strip("'\" ").split("?")[0].split("#")[0])
        if limpo.startswith(("http://", "https://", "//", "data:")):
            return True
        return (os.path.exists(os.path.join(assets, limpo)) or
                os.path.exists(os.path.join(assets, os.path.basename(limpo))))

    reparadas = [0]

    def reparar(m):
        """Se o caminho literal não resolve mas o arquivo está em assets/
        com o mesmo nome, aponta para ele. Cobre a variante "?#iefix" e
        caminhos relativos com profundidade errada."""
        bruto = m.group(1).strip()
        limpo_q = bruto.strip("'\" ")
        if limpo_q.startswith(("http://", "https://", "//", "data:")):
            return m.group(0)
        alvo = unquote(limpo_q.split("?")[0].split("#")[0])
        if os.path.exists(os.path.join(assets, alvo)):
            return m.group(0)
        base_a = os.path.basename(alvo)
        if base_a and os.path.exists(os.path.join(assets, base_a)):
            reparadas[0] += 1
            return "url(" + base_a + ")"
        return m.group(0)

    for fn in sorted(os.listdir(assets)):
        if not fn.endswith(".css"):
            continue
        cp = os.path.join(assets, fn)
        c = io.open(cp, encoding="utf-8", errors="replace").read()
        c = re.sub(r"url\(([^)]*)\)", reparar, c)

        def fix_src(m):
            nonlocal podadas, intactas
            corpo = m.group(1)
            partes = [p.strip() for p in corpo.split(",")]
            bons = []
            for parte in partes:
                u = re.search(r"url\(([^)]*)\)", parte)
                if not u or existe(u.group(1)):
                    bons.append(parte)
            fim = m.group(2)
            if not bons or len(bons) == len(partes):
                intactas += len(partes) - len(bons)
                return m.group(0)
            podadas += len(partes) - len(bons)
            sep = "\n\t\t" if "\n" in corpo else " "
            return "src:" + sep + ("," + sep).join(bons) + fim

        # o terminador pode ser ";" ou o "}" do bloco — sem aceitar os dois,
        # a última declaração de cada regra escapava da poda.
        c = re.sub(r"src\s*:\s*([^;{}]+)([;}])", fix_src, c)
        io.open(cp, "w", encoding="utf-8", errors="replace").write(c)

    if reparadas[0]:
        print("CSS reparado: %d refs remapeadas para o arquivo local" % reparadas[0])
    if podadas or intactas:
        print("CSS podado: %d refs mortas removidas" % podadas +
              (" (%d mantidas: nenhuma alternativa válida)" % intactas if intactas else ""))
    return podadas


def reconstruir(d, nome=None, offline=False, manter_trackers=False, bloquear="",
                marcar=False, redirect="", so_frontend=False, link=""):
    """Monta o clone local a partir de um dicionário de captura.

    Mesmo formato produzido por capturar.js (navegador) e por
    clonar-direto.py (terminal): assim os dois caminhos compartilham toda a
    limpeza, a reescrita de caminhos e a auditoria.
    """
    class _Args:
        pass
    a = _Args()
    a.offline, a.manter_trackers, a.marcar = offline, manter_trackers, marcar
    a.so_frontend = so_frontend
    a.link = link

    if bloquear:
        TRACKER_SRC.extend(x.strip() for x in bloquear.split(",") if x.strip())

    page_url, files = d["pageUrl"], d["files"]
    html = d["html"]

    nome = nome or re.sub(r"[^a-z0-9]+", "-", urlsplit(page_url).hostname.lower()).strip("-")
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
            html, k = trocar(html, v, tok)
            if k:
                n += k; achou = True
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
    # Um script de tracker já teve o src reescrito para assets/xxx.js, então
    # "mxj5trk" some do src. Este mapa recupera a URL de origem para a
    # marcação decidir pelo domínio real, não pelo nome local.
    local2url = {v.split("?")[0]: k for k, v in url2local.items()}
    mortos = []
    if not a.manter_trackers:
        def mata(m):
            attrs, corpo = m.group(1), m.group(2)
            if "data-clone-disabled" in attrs:
                return m.group(0)
            src = re.search(r'src="([^"]*)"', attrs)
            porque = None
            if src:
                alvo = src.group(1)
                origem = local2url.get(alvo.split("?")[0], "")
                for t in TRACKER_SRC:
                    if t in alvo or (origem and t in origem): porque = t; break
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

        # pixels são <img>/<iframe>, não <script>: bloquear só o download
        # deixaria a tag apontando para o rastreador e ela dispararia igual.
        px = [0]

        def mata_pixel(m):
            tag, attrs = m.group(1), m.group(2)
            src = re.search(r'src="([^"]*)"', attrs)
            if not src or not eh_tracker(src.group(1)):
                return m.group(0)
            limpo = re.sub(r'\ssrc="[^"]*"', "", attrs)
            px[0] += 1
            return '<%s%s data-clone-disabled="pixel">' % (tag, limpo)

        html = re.sub(r"<(img|iframe)([^>]*)>", mata_pixel, html)
        print("rastreadores encontrados: %d scripts, %d iframes, %d pixels"
              % (len(mortos), n_ifr + n_ns, px[0]))

        if not a.marcar:
            # LIMPEZA TOTAL: tira o que foi marcado em vez de só desativar,
            # e mais tudo que amarra a página ao servidor de origem.
            c = {}
            html, c["scripts"] = re.subn(
                r"<script\b[^>]*data-clone-disabled[^>]*>.*?</script>\s*", "", html, flags=re.S)
            html, c["pixels"] = re.subn(
                r"<(?:img|iframe)\b[^>]*data-clone-disabled[^>]*>\s*", "", html)
            html, c["noscript"] = re.subn(
                r"<noscript>\s*(?:<!--[^>]*-->)?\s*</noscript>\s*", "", html)
            # preconnect/dns-prefetch/preload para fora: só abrem conexão
            html, c["prefetch"] = re.subn(
                r'<link\b[^>]*rel="(?:preconnect|dns-prefetch|prefetch|preload)"[^>]*href="https?://[^"]*"[^>]*>\s*',
                "", html)
            html, c["prefetch2"] = re.subn(
                r'<link\b[^>]*href="https?://[^"]*"[^>]*rel="(?:preconnect|dns-prefetch|prefetch|preload)"[^>]*>\s*',
                "", html)
            # CSP herdada barra arquivo local
            html, c["csp"] = re.subn(
                r'<meta\b[^>]*http-equiv="[Cc]ontent-[Ss]ecurity-[Pp]olicy"[^>]*>\s*', "", html)
            # integrity/nonce conferem hash do CDN e reprovam o arquivo local
            html, c["attrs"] = re.subn(r'\s(?:integrity|nonce)="[^"]*"', "", html)
            html, c["cross"] = re.subn(r'\scrossorigin(?:="[^"]*")?', "", html)
            # links externos viram inertes
            html, c["links"] = re.subn(
                r'(<a\b[^>]*href=")https?://[^"]*(")',
                lambda m: m.group(1) + "#" + m.group(2), html)
            # atributos que guardam URL de destino do funil
            html, c["dataurl"] = re.subn(
                r'\s(?:data-go-to|data-href|data-url|data-redirect)="https?://[^"]*"', "", html)

            if a.so_frontend:
                # Só o frontend: remove TODO o JavaScript restante (UI,
                # anti-bot, verificação de tráfego, cloaking). Sobram só
                # HTML/CSS/imagens/fontes — e o redirect, injetado depois.
                # Sem scripts do site, os stubs também são dispensáveis.
                html, c["js"] = re.subn(
                    r"<script\b(?![^>]*data-clone)[^>]*>.*?</script>\s*", "", html, flags=re.S)
                html, c["jssrc"] = re.subn(
                    r"<script\b(?![^>]*data-clone)[^>]*/?>\s*", "", html)
                html, c["onattr"] = re.subn(r'\son\w+="[^"]*"', "", html)
            else:
                html = re.sub(r"(<head\b[^>]*>)", lambda m: m.group(1) + STUBS, html, count=1)
            print("LIMPEZA: %s" % ", ".join("%s=%d" % (k, v) for k, v in c.items() if v))

    if link:
        # Escopo simples (o padrão): troca o href de cada <a> pela URL, e tira
        # onclick/target para que o hover mostre a URL e o clique vá até ela.
        # Não mexe em nada além dos <a>.
        alvo = link.replace("\\", "\\\\").replace('"', "&quot;")

        def troca_a(m):
            tag = m.group(0)
            if 'href="' in tag:
                tag = re.sub(r'href="[^"]*"', 'href="%s"' % alvo, tag, count=1)
            else:
                tag = tag[:2] + ' href="%s"' % alvo + tag[2:]
            tag = re.sub(r'\son\w+="[^"]*"', "", tag)
            tag = re.sub(r'\starget="[^"]*"', "", tag)
            return tag

        html, n_link = re.subn(r"<a\b[^>]*>", troca_a, html)
        print("LINK nos <a>: %d -> %s" % (n_link, link))

    if redirect:
        # depois da limpeza: entra no fim do <body> para rodar por último
        snip = redirect_snippet(redirect)
        if "</body>" in html:
            html = html.replace("</body>", snip + "\n</body>", 1)
        else:
            html += snip
        print("REDIRECT: todo clique -> %s" % redirect)
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

    # ── 4c. poda referências mortas nos CSS ───────────────────────
    if not a.marcar:
        podar_css(assets)

    # ── 5. auditoria ──────────────────────────────────────────────
    vivo = re.sub(r"<script\b[^>]*data-clone-disabled.*?</script>", "", html, flags=re.S)

    # assets = o que o navegador busca sozinho (src, e href de <link>)
    assets_ref = set(m.group(1) for m in re.finditer(
        r'src="(?!https?:|//|data:|chrome-extension)([^"]+)"', vivo))
    assets_ref |= set(m.group(1) for m in re.finditer(
        r'<link[^>]+href="(?!https?:|//|data:)([^"]+)"', vivo))
    # refs dentro dos CSS também contam: é onde vivem ícones e backgrounds
    css_ref = {}
    for fn in os.listdir(assets):
        if not fn.endswith(".css"):
            continue
        c = io.open(os.path.join(assets, fn), encoding="utf-8", errors="replace").read()
        for m in re.finditer(r"url\(\s*['\"]?(?!data:)([^'\")]+)", c):
            u = m.group(1).strip()
            if u.startswith(("http://", "https://", "//")):
                continue
            limpo = unquote(u.split("?")[0].split("#")[0])
            base_u = os.path.basename(limpo)
            if not os.path.exists(os.path.join(assets, limpo)) and \
               not os.path.exists(os.path.join(assets, base_u)):
                css_ref.setdefault(base_u, fn)

    faltando = sorted(r for r in assets_ref if not os.path.exists(
        os.path.join(out, unquote(r.split("?")[0]))))

    # o que já dava 404 no site de origem não é buraco nosso — o log da
    # captura registra isso, então dá para separar as duas coisas.
    log404 = set()
    for l in d.get("log", []):
        if l.startswith("HTTP404") or l.startswith("HTTP403"):
            log404.add(os.path.basename(l.split("?")[0].split("#")[0]))

    css_nossos = {k: v for k, v in css_ref.items() if k not in log404}
    css_origem = len(css_ref) - len(css_nossos)

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
    print("assets referenciados no HTML: %d | faltando: %d" % (len(assets_ref), len(faltando)))
    for f in faltando:
        marca = "  (já dava 404 na origem)" if os.path.basename(
            f.split("?")[0]) in log404 else ""
        print("   FALTA:", f, marca)
    if css_ref:
        print("refs quebradas dentro dos CSS: %d  (%d já davam 404 na origem)"
              % (len(css_ref), css_origem))
        for k, v in sorted(css_nossos.items())[:12]:
            print("   FALTA: %s  (citado em %s)" % (k, v))
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


def main():
    ap = argparse.ArgumentParser(description="Reconstrói um clone a partir da captura JSON")
    ap.add_argument("json", help="arquivo gerado por capturar.js")
    ap.add_argument("nome", nargs="?", help="nome da pasta do clone (padrão: host da página)")
    ap.add_argument("--manter-trackers", action="store_true",
                    help="não mexe nos scripts de rastreamento")
    ap.add_argument("--marcar", action="store_true",
                    help="só marca os rastreadores (type=text/plain) em vez de removê-los")
    ap.add_argument("--link", default="", metavar="URL",
                    help="troca o href de todos os <a> por esta URL (só os <a>)")
    ap.add_argument("--redirect", default="", metavar="URL",
                    help="(avançado) intercepta todo clique de CTA e leva a esta URL")
    ap.add_argument("--so-frontend", action="store_true",
                    help="remove TODO o JavaScript (UI, anti-bot, verificação "
                         "de tráfego), deixando só HTML/CSS/imagens + o redirect")
    ap.add_argument("--offline", action="store_true",
                    help="não tenta baixar do terminal os assets externos que sobraram")
    ap.add_argument("--bloquear", default="",
                    help="trechos de URL extras a neutralizar, separados por vírgula "
                         "(para analytics em domínio próprio)")
    a = ap.parse_args()
    if not os.path.exists(a.json):
        sys.exit("ERRO: %s não encontrado" % a.json)
    reconstruir(json.load(open(a.json)), a.nome,
                offline=a.offline, manter_trackers=a.manter_trackers,
                bloquear=a.bloquear, marcar=a.marcar, redirect=a.redirect,
                so_frontend=a.so_frontend, link=a.link)


if __name__ == "__main__":
    main()
