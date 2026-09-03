#!/usr/bin/env python3
"""
CLONADOR DE PÁGINAS — passo 2 de 2: RECONSTRUÇÃO

Uso:  ./clonar.py ~/Downloads/captura-exemplo-com.json [nome-do-clone]

Lê o JSON gerado por capturar.js e monta um clone local autocontido:
grava os assets, reescreve HTML e CSS para caminhos locais, neutraliza
rastreadores e audita o resultado.
"""
import argparse, base64, hashlib, io, json, os, re, sys, time
from html.parser import HTMLParser
from urllib.parse import urlsplit, unquote, urljoin

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

# Domínios/redes que são rastreamento sem ambiguidade nenhuma. Ganham de
# tudo: nem a whitelist de UI salva um script servido por um destes.
TRACKER_DOMINIOS = [
    "chrome-extension://", "moz-extension://",
    "googletagmanager", "google-analytics", "analytics.google", "doubleclick",
    "clarity.ms", "posthog", "cloudflareinsights", "connect.facebook",
    "facebook.net", "facebook.com/tr", "hotjar", "segment.io", "segment.com",
    "mixpanel", "amplitude", "tiktok", "bat.bing.com", "criteo", "taboola",
    "outbrain", "newrelic", "sentry.io", "datadoghq", "snapchat", "sc-static",
    "pinterest", "reddit.com/rp", "linkedin.com/px", "licdn.com",
    # redes de afiliado/CPA: pixel de conversão, postback e cloaking
    "maxweb", "everflow", "voluum", "redtrack", "binom", "clickmagick",
    "cloaker", "trackier", "affise", "hasoffers", "cake-affiliate",
    # plataformas de consentimento (CMP): existem para registrar e enviar
    # a escolha do visitante, e trazem o tracking junto
    "cookiebot", "onetrust", "cookielaw", "osano", "quantcast", "trustarc",
    "didomi", "iubenda", "usercentrics", "termly", "cookieyes", "complianz",
    "civiccomputing", "sourcepoint", "consentmanager",
]

# Frontend puro. Um arquivo com um destes no nome MANTÉM, mesmo que case com
# algum padrão frouxo da TRACKER_SRC ("/track.js" x "slick-track.js", por
# exemplo). É o lado seguro do CLAUDE.md: remover UI quebra a página.
UI_KEEP = [
    "language", "lang.selector", "i18n", "locale", "translat",
    "slider", "swiper", "splide", "owl", "slick", "glide", "flickity",
    "carousel", "accordion", "collapse", "countdown", "timer", "counter",
    "animate", "animation", "wow.min", "aos.", "scrollreveal", "gsap",
    "lightbox", "fancybox", "magnific", "modal", "popper", "tooltip",
    "jquery", "bootstrap", "popup", "mask", "inputmask", "validate",
    "flatpickr", "datepicker", "lazyload", "lazysizes", "smooth-scroll",
    "menu", "navbar", "hamburger", "tabs.", "select2", "choices",
]

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
    "/conversion/iframe", "/conversion/pixel", "/postback", "/pixel.gif",
    "/collect?", "/beacon", "/impression",
    # PostHog atrás de proxy próprio: a chave de projeto começa sempre por
    # "phc_" e o SDK carrega de /array/<chave>/ — pega o config.js disfarçado.
    "phc_", "/array/phc",
]
TRACKER_INLINE = [
    "dataLayer", "gtag(", "posthog.init", "__CF$cv", "_conv_q", "window.convert",
    "GTM-", "clarity", "fbq(", "ttq.", "_hjSettings", "analytics.load",
    "mixpanel.init", "amplitude.getInstance", "Sentry.init", "newrelic",
    # tracking de rede de afiliado inline (Everflow, mxj5trk e afins)
    "mxj5trk", "EF.click", "EF.conversion", "EF.urlParameter", "everflow",
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
            'lightbox|tooltip|counter|countdown|timer|lang|idioma|locale|switcher/i;\n'
            'function cls(el){if(!el||el.className==null)return "";'
            'var c=el.className;return (c.baseVal!==undefined?c.baseVal:c)+"";}\n'
            'function ui(el){while(el&&el!==document.documentElement){'
            'if(UI.test(cls(el)))return true;'
            'if(el.getAttribute){if(el.hasAttribute("data-clone-lang")||el.hasAttribute("data-clone-ui"))return true;'
            'if(UI.test(el.getAttribute("id")||""))return true;'
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


# ══════════════════════════════════════════════════════════════════
#  IDIOMAS
#  Todo clone sai com um seletor de idioma próprio, injetado, que não
#  depende do frontend da página: um botão flutuante isolado em Shadow
#  DOM. A troca acontece na hora, trocando o texto pelo dicionário —
#  sem recarregar, sem query string, sem servidor, sem chamada externa.
# ══════════════════════════════════════════════════════════════════
IDIOMAS_NOME = {
    "pt-br": "Português (Brasil)", "pt": "Português", "en": "English",
    "es": "Español", "fr": "Français", "de": "Deutsch", "it": "Italiano",
    "nl": "Nederlands", "sv": "Svenska", "no": "Norsk", "da": "Dansk",
    "fi": "Suomi", "pl": "Polski", "cs": "Čeština", "ro": "Română",
    "hu": "Magyar", "el": "Ελληνικά", "tr": "Türkçe", "ru": "Русский",
    "uk": "Українська", "ar": "العربية", "he": "עברית", "hi": "हिन्दी",
    "id": "Bahasa Indonesia", "th": "ไทย", "vi": "Tiếng Việt",
    "ja": "日本語", "ko": "한국어", "zh-hans": "简体中文", "zh-hant": "繁體中文",
    "zh": "中文",
}
IDIOMAS_PADRAO = ["en", "es", "pt-br", "fr", "de", "it", "ja", "zh-hans"]

# A tabela acima é só um atalho de nomes. O clone aceita QUALQUER sigla
# BCP-47 — "sw", "vi", "af-za", "sr-latn" — e o nome no menu sai do
# Intl.DisplayNames do navegador, no próprio idioma.
CODIGO_RE = re.compile(r"^[a-z]{2,3}(-[a-z0-9]{2,8}){0,2}$")

# Escrita da direita para a esquerda: sem isto o texto entra invertido.
RTL = {"ar", "he", "fa", "ur", "ps", "sd", "ug", "yi", "dv", "ku", "ckb", "arc"}


def valida_codigo(c):
    return bool(CODIGO_RE.match(c))


def eh_rtl(c):
    return c.split("-")[0] in RTL
IGNORA_TEXTO = {"script", "style", "noscript", "template", "svg", "code", "pre"}
ATRIB_TEXTO = ("alt", "title", "placeholder", "aria-label")


class _Segmentos(HTMLParser):
    """Coleta o texto traduzível de um HTML, na ordem do documento.

    Ordem importa: é ela que alinha a página original com a versão que o
    servidor devolveu traduzida, já que as duas saem do mesmo template.
    """

    VAZIAS = {"br", "img", "input", "hr", "meta", "link", "source", "area",
              "base", "col", "embed", "param", "track", "wbr"}

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.mudo = []
        self.textos = []
        self.atributos = []
        self.titulo = ""
        self._em_titulo = False
        # Caminho no DOM de cada trecho. Casar a página com a versão
        # traduzida por POSIÇÃO é tudo-ou-nada; por caminho, o que existe
        # nas duas casa e o resto simplesmente fica de fora.
        self.pilha = [["", {}]]
        self.cam_textos = []
        self.cam_atributos = []
        self._ntxt = {}

    def _caminho(self):
        return "/".join(q[0] for q in self.pilha[1:])

    def _push(self, tag):
        cont = self.pilha[-1][1]
        cont[tag] = cont.get(tag, 0) + 1
        self.pilha.append(["%s[%d]" % (tag, cont[tag]), {}])

    def handle_starttag(self, tag, attrs):
        # "English", "日本語" e afins são rótulos do seletor: cada um já está
        # no próprio idioma e traduzi-los seria o oposto do que se quer.
        rotulo = any(k in ("data-value", "data-lang", "data-language",
                           "data-locale", "hreflang", "data-clone-lang")
                     and (v or "").strip().lower() in IDIOMAS_NOME
                     for k, v in attrs)
        vazia = tag in self.VAZIAS
        if not vazia:
            self._push(tag)
        if tag in IGNORA_TEXTO or rotulo:
            self.mudo.append(tag)
        if tag == "title":
            self._em_titulo = True
        if self.mudo:
            return
        base = self._caminho() + ("/" + tag if vazia else "")
        for k, v in attrs:
            if k in ATRIB_TEXTO and v and v.strip() and _traduzivel(v):
                self.atributos.append(v.strip())
                self.cam_atributos.append(base + "@" + k)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if self.mudo and self.mudo[-1] == tag:
            self.mudo.pop()
        if tag == "title":
            self._em_titulo = False
        if tag not in self.VAZIAS:
            for i in range(len(self.pilha) - 1, 0, -1):
                if self.pilha[i][0].split("[")[0] == tag:
                    del self.pilha[i:]
                    break

    def handle_data(self, dado):
        if self._em_titulo:
            self.titulo = dado.strip()
            return
        if self.mudo:
            return
        t = dado.strip()
        if t and _traduzivel(t):
            self.textos.append(t)
            cam = self._caminho()
            self._ntxt[cam] = self._ntxt.get(cam, 0) + 1
            self.cam_textos.append("%s#%d" % (cam, self._ntxt[cam]))


def _traduzivel(t):
    """Só entra o que é frase de gente: precisa ter letra e não ser código."""
    t = t.strip()
    if len(t) < 2 or len(t) > 3000:
        return False
    if not re.search(r"[A-Za-zÀ-ÖØ-öø-ÿĀ-ɏͰ-῿぀-퟿]", t):
        return False
    if re.match(r"^[\d\s.,:;/%+-]+$", t):
        return False
    if t.startswith(("{", "[", "<", "//", "/*")) or "function(" in t:
        return False
    return True


def segmentos(html):
    p = _Segmentos()
    try:
        p.feed(html)
    except Exception:
        pass
    return p


def dicionario_da_variante(html_base, html_var):
    """Casa a página com a versão que o servidor devolveu traduzida.

    Casar por posição era tudo-ou-nada: um parágrafo a mais na versão
    traduzida e o alinhamento inteiro ia fora — foi o que descartou as nove
    traduções oficiais da Vanotium por UM atributo de diferença. Agora o par
    é feito pelo caminho no DOM; o que sobra vai para tradução.
    """
    b, v = segmentos(html_base), segmentos(html_var)
    pares, d = 0, {}
    for cams_b, txt_b, cams_v, txt_v in (
            (b.cam_textos, b.textos, v.cam_textos, v.textos),
            (b.cam_atributos, b.atributos, v.cam_atributos, v.atributos)):
        mapa_v = dict(zip(cams_v, txt_v))
        for cam, o in zip(cams_b, txt_b):
            t = mapa_v.get(cam)
            if t is None:
                continue
            pares += 1
            if t and o != t:
                d.setdefault(o, t)
    if b.titulo and v.titulo and b.titulo != v.titulo:
        d[b.titulo] = v.titulo
    total = len(b.textos) + len(b.atributos)
    return d, (pares / float(total) if total else 0.0)


# ── página que não é a página ────────────────────────────────────
# Cloudflare e afins devolvem 200 com um HTML de bloqueio ou de desafio.
# Sem reconhecer isso, o clonador empacota a tela de erro achando que é o
# site — foi o que aconteceu com buyskyline.co.
BLOQUEIO = [
    "sorry, you have been blocked", "attention required", "access denied",
    "you are unable to access", "you have been blocked", "acesso negado",
    "você foi bloqueado", "voce foi bloqueado", "403 forbidden",
    "error 1020", "error 1015", "error 1006", "ip address has been banned",
    "request blocked", "acesso restrito", "not available in your country",
    "não está disponível no seu país", "blocked by the network",
]
DESAFIO = [
    "just a moment", "um momento", "checking your browser",
    "verifying you are human", "verificando se você é humano",
    "verificando o seu navegador", "enable javascript and cookies",
    "please enable cookies", "ddos protection by", "challenge-platform",
    "cf-challenge", "cf_chl_opt", "__cf_chl", "turnstile",
]


def diagnostica_pagina(html, titulo="", texto="", recursos=None):
    """Diz se o que veio é a página mesmo, um desafio ou um bloqueio.

    Devolve (situacao, motivo) com situacao em ok/desafio/bloqueado.
    Bloqueio e desafio pedem coisas diferentes: desafio às vezes passa com
    janela na tela; bloqueio é a rede recusando o IP — só troca de saída.
    """
    baixo = ((titulo or "") + " " + (texto or "")[:4000] + " "
             + html[:8000]).lower()
    for m in BLOQUEIO:
        if m in baixo:
            return "bloqueado", m
    for m in DESAFIO:
        if m in baixo:
            return "desafio", m
    # sinal de forma: quase nada de texto e quase nenhum recurso
    if texto is not None and len((texto or "").strip()) < 250 and \
            (recursos is not None and recursos <= 3) and \
            "cloudflare" in baixo:
        return "bloqueado", "página vazia servida pelo Cloudflare"
    return "ok", ""


def normaliza_codigo(c):
    """pt_BR, PT-br, "pt-BR " -> pt-br. Devolve "" se não for BCP-47."""
    c = (c or "").strip().replace("_", "-").lower()
    c = re.split(r"[,;\s]", c)[0]
    return c if valida_codigo(c) else ""


def idioma_da_pagina(html, amostra=None):
    """Descobre em que idioma a página está — pela própria página.

    Ordem: o que o HTML declara (lang do <html>, xml:lang, meta de idioma)
    e, se ele não declarar nada, o texto que ele contém. Nunca um padrão
    chutado: dizer "é português" para uma página em inglês faria o clonador
    traduzir de um idioma para ele mesmo.
    """
    padroes = [
        r"<html\b[^>]*\blang\s*=\s*[\"']([^\"']+)",
        r"<html\b[^>]*\bxml:lang\s*=\s*[\"']([^\"']+)",
        r"<html\b[^>]*\blang\s*=\s*([A-Za-z][\w-]*)",
        r"<meta\b[^>]*http-equiv\s*=\s*[\"']content-language[\"'][^>]*content\s*=\s*[\"']([^\"']+)",
        r"<meta\b[^>]*content\s*=\s*[\"']([^\"']+)[\"'][^>]*http-equiv\s*=\s*[\"']content-language",
        r"<meta\b[^>]*name\s*=\s*[\"']language[\"'][^>]*content\s*=\s*[\"']([^\"']+)",
        r"<meta\b[^>]*property\s*=\s*[\"']og:locale[\"'][^>]*content\s*=\s*[\"']([^\"']+)",
    ]
    for pat in padroes:
        m = re.search(pat, html, re.I)
        if m:
            c = normaliza_codigo(m.group(1))
            if c:
                return c, "declarado no HTML"
    if amostra:
        c = detectar_idioma(amostra)
        if c:
            return c, "detectado pelo texto da página"
    return "", "não declarado"


def detectar_idioma(termos):
    """Último recurso: pergunta ao Claude em que idioma o texto está."""
    import subprocess
    trecho = [t for t in termos if len(t) > 25][:12] or list(termos)[:12]
    if not trecho:
        return ""
    try:
        r = subprocess.run(
            ["claude", "-p",
             "Em que idioma está este texto? Responda SÓ o código BCP-47 "
             "(ex.: en, pt-br, de, zh-hans), nada mais.\n\n"
             + "\n".join(trecho)],
            capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL)
    except Exception:
        return ""
    return normaliza_codigo((r.stdout or "").strip().splitlines()[0]
                            if (r.stdout or "").strip() else "")


CACHE_TRIAGEM = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             ".veredictos.json")


def _amostra_script(texto, limite=2600):
    """Pedaço do script que revela a intenção sem estourar o pedido.

    O começo é onde ficam a config e as chaves de projeto; o resto é
    minificação. Um trecho do meio ajuda a pegar o envio de dados.
    """
    texto = texto or ""
    if len(texto) <= limite:
        return texto
    meio = len(texto) // 2
    return (texto[:limite * 2 // 3] + "\n…\n"
            + texto[meio:meio + limite // 3])


def triagem_scripts(indecisos, quieto=False):
    """O que as regras não decidem, a LLM decide: interface ou rastreamento?

    As listas cobrem o que já se conhece. Um rastreador novo, ou servido de
    um domínio próprio, não casa com nada e hoje passa direto — o lado
    seguro do CLAUDE.md manda manter, e manter é o certo quando ninguém
    olhou. Aqui alguém olha.

    O veredicto é gravado por hash do conteúdo em .veredictos.json, então
    cada script é julgado uma vez só, para sempre, em qualquer clone.
    """
    import subprocess
    if not indecisos:
        return {}
    cache = {}
    if os.path.exists(CACHE_TRIAGEM):
        try:
            cache = json.load(io.open(CACHE_TRIAGEM, encoding="utf-8"))
        except Exception:
            cache = {}

    veredicto, novos = {}, []
    for it in indecisos:
        h = hashlib.sha1((it["origem"] + "\x00" + it["texto"]).encode(
            "utf-8", "replace")).hexdigest()
        it["hash"] = h
        if h in cache:
            veredicto[it["id"]] = cache[h]
        else:
            novos.append(it)

    if novos:
        linhas = []
        for n, it in enumerate(novos, 1):
            linhas.append("### %d\nURL de origem: %s\nTrecho:\n%s"
                          % (n, it["origem"] or "(script inline na página)",
                             _amostra_script(it["texto"])))
        prompt = (
            "Você tria scripts de uma landing page que está sendo clonada para "
            "rodar em localhost, sem rastreamento.\n\n"
            "Para CADA script abaixo, classifique:\n"
            '- "interface": manipula a página — FAQ, slider, cronômetro, menu, '
            "animação, máscara, validação, seletor de idioma, lazy-load, "
            "vídeo, biblioteca de UI (jQuery, bootstrap, swiper…).\n"
            '- "rastreamento": manda dados de navegação para terceiros — '
            "analytics, pixel, session replay, heatmap, A/B testing, "
            "postback de afiliado, fingerprinting, detecção de bot.\n"
            '- "misto": faz as duas coisas.\n\n'
            "REGRA DE OURO: na dúvida, responda \"interface\". Remover um "
            "script de UI quebra a página; manter um rastreador num clone "
            "local é inofensivo. Só responda \"rastreamento\" se o script "
            "existir PARA rastrear.\n\n"
            "Responda SÓ um objeto JSON: chave = o número do script, valor = "
            '{"classe": "...", "porque": "<até 8 palavras>"}\n\n'
            + "\n\n".join(linhas))
        try:
            r = subprocess.run(["claude", "-p", prompt], capture_output=True,
                               text=True, timeout=600, stdin=subprocess.DEVNULL)
            txt = (r.stdout or "").strip()
            if "```" in txt:
                txt = re.sub(r"^.*?```(?:json)?\s*|\s*```.*$", "", txt, flags=re.S)
            i, f = txt.find("{"), txt.rfind("}")
            m = json.loads(txt[i:f + 1]) if i >= 0 and f > i else {}
        except Exception as e:
            if not quieto:
                print("   triagem indisponível (%s) — tudo mantido" % e)
            m = {}
        for n, it in enumerate(novos, 1):
            v = m.get(str(n)) or m.get(n) or {}
            classe = (v.get("classe") or "").strip().lower()
            if classe not in ("interface", "rastreamento", "misto"):
                classe = "interface"          # sem resposta clara: mantém
            reg = {"classe": classe, "porque": (v.get("porque") or "")[:60]}
            cache[it["hash"]] = reg
            veredicto[it["id"]] = reg
        try:
            io.open(CACHE_TRIAGEM, "w", encoding="utf-8").write(
                json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True))
        except Exception:
            pass
    return veredicto


# Globais que o navegador já tem — nunca viram stub.
NATIVOS = set("""
Math JSON Object Array String Number Boolean Date Promise Intl RegExp Error
Map Set WeakMap WeakSet Symbol Reflect Proxy BigInt Function console window
document navigator location history screen localStorage sessionStorage
performance URL URLSearchParams FormData Headers Request Response Blob File
FileReader XMLHttpRequest AbortController Element Node HTMLElement Event
CustomEvent MutationObserver IntersectionObserver ResizeObserver Image Audio
Video Worker Notification CSS NodeList DOMParser TextEncoder TextDecoder
ArrayBuffer Uint8Array Int8Array Float32Array DataView Atomics WebAssembly
""".split())

_DEF_RE = (r"(?:window\.%s\s*=|\bvar\s+%s\s*=|\blet\s+%s\s*=|\bconst\s+%s\s*=|"
           r"\bfunction\s+%s\b|\b%s\s*=\s*(?:function|\{|\[))")


def _define(js, nome):
    n = re.escape(nome)
    return re.search(_DEF_RE % (n, n, n, n, n, n), js) is not None


def stubs_orfaos(js_fica, js_saiu):
    """Stubs para os globais que saíram junto com um script removido.

    Tirar o SDK de rastreamento e deixar o JS de interface chamando
    `EF.click()` dá ReferenceError, e o erro derruba o resto do arquivo — a
    página perde justamente a UI que a limpeza queria proteger. Aqui, todo
    global que o JS que FICOU chama, que ele não define, e que o JS REMOVIDO
    definia, ganha um objeto inerte com os métodos certos.
    """
    usados = {}
    for m in re.finditer(r"(?<![\w.$])([A-Za-z_$][\w$]*)\.([A-Za-z_$][\w$]*)\s*\(",
                         js_fica):
        nome, metodo = m.group(1), m.group(2)
        if nome in NATIVOS or len(nome) < 2:
            continue
        usados.setdefault(nome, set()).add(metodo)

    orfaos = {n: ms for n, ms in usados.items()
              if not _define(js_fica, n) and _define(js_saiu, n)}
    if not orfaos:
        return "", {}
    partes = []
    for n in sorted(orfaos):
        corpo = ",".join('%s:function(){return "";}' % m for m in sorted(orfaos[n]))
        partes.append("window.%s=window.%s||{%s};" % (n, n, corpo))
    return ('<script data-clone="stubs-orfaos">\n'
            '/* globais que saíram com os rastreadores; sem eles o JS de '
            'interface quebraria */\n' + "\n".join(partes) + "\n</script>"), orfaos


def neutraliza_externos(html):
    """Corta o que ainda carregaria de fora sozinho ao abrir a página.

    As listas e a triagem pegam o que se reconhece. Isto é a rede embaixo:
    se depois de tudo alguma tag ainda aponta para http(s) e é buscada
    sozinha, ela sai — seja tracker que ninguém reconheceu, seja asset que
    não veio no download. Um clone que telefona para fora não é um clone.

    Clicar continua livre: <a href> não é tocado aqui.
    """
    c, dominios = {}, set()

    def anota(u):
        m = re.match(r"https?://([^/\s\"']+)", u or "")
        if m:
            dominios.add(m.group(1).lower())

    def fora(m):
        anota(m.group(0))
        return ""

    ext = r'(?:src|data-src|href)\s*=\s*"https?://'
    html, c["scripts"] = re.subn(
        r'<script\b(?![^>]*data-clone)[^>]*' + ext + r'[^"]*"[^>]*>.*?</script>\s*',
        fora, html, flags=re.S | re.I)
    html, c["iframes"] = re.subn(
        r'<iframe\b[^>]*' + ext + r'[^"]*"[^>]*>.*?</iframe>\s*',
        fora, html, flags=re.S | re.I)
    html, c["iframes2"] = re.subn(
        r'<iframe\b[^>]*' + ext + r'[^"]*"[^>]*>\s*', fora, html, flags=re.I)
    html, c["links"] = re.subn(
        r'<link\b[^>]*href\s*=\s*"https?://[^"]*"[^>]*>\s*', fora, html, flags=re.I)

    # imagem e <source>: a tag fica (o layout depende dela), o endereço sai
    def limpa_media(m):
        tag = m.group(0)
        if not re.search(r'(?:src|srcset|poster)\s*=\s*"https?://', tag, re.I):
            return tag
        for a in ("src", "srcset", "poster", "data-src", "data-srcset"):
            v = re.search(r'\b%s\s*=\s*"([^"]*)"' % a, tag, re.I)
            if v and re.search(r"https?://", v.group(1)):
                anota(v.group(1))
                tag = re.sub(r'\s\b%s\s*=\s*"[^"]*"' % a, "", tag, flags=re.I)
                c["media"] = c.get("media", 0) + 1
        return tag.replace(">", ' data-clone-disabled="externo">', 1)

    html = re.sub(r"<(?:img|source|video|audio)\b[^>]*>", limpa_media, html, flags=re.I)

    # background externo em style inline
    def limpa_style(m):
        anota(m.group(1))
        c["style"] = c.get("style", 0) + 1
        return "url()"

    html = re.sub(r'url\(\s*[\'"]?(https?://[^)\'"]+)[\'"]?\s*\)', limpa_style, html)
    return html, {k: v for k, v in c.items() if v}, sorted(dominios)


def regra_script(attrs, corpo, local2url):
    """Decide um <script> pelas listas. Devolve (porque, chave, origem).

    porque=None significa "as regras não sabem" — é o que vai para a triagem.
    Uma função só para não haver duas versões da regra andando separadas.
    """
    src = re.search(r'src="([^"]*)"', attrs)
    if src:
        alvo = src.group(1)
        # o src pode ter virado "assets/xxx.js" e escondido o domínio:
        # a decisão olha a URL de ORIGEM.
        origem = local2url.get(alvo.split("?")[0], "") or alvo
        u = (origem + " " + alvo).lower()
        for t in TRACKER_DOMINIOS:
            if t in u:
                return t, alvo, origem
        if not any(k in u for k in UI_KEEP):
            for t in TRACKER_SRC:
                if t in u:
                    return t, alvo, origem
        return None, alvo, origem
    for t in TRACKER_INLINE:
        if t in corpo:
            return t, None, ""
    chave = "inline:" + hashlib.sha1(corpo.encode("utf-8", "replace")).hexdigest()
    return None, chave, ""


def coletar_indecisos(html, local2url, assets, minimo=200):
    """Os scripts que as listas não julgaram — só eles vão para a LLM."""
    itens, vistos = [], set()
    for m in re.finditer(r"<script\b([^>]*)>(.*?)</script>", html, re.S):
        attrs, corpo = m.group(1), m.group(2)
        if "data-clone" in attrs:
            continue                       # nosso, ou já marcado
        porque, chave, origem = regra_script(attrs, corpo, local2url)
        if porque or not chave or chave in vistos:
            continue
        if chave.startswith("inline:"):
            texto = corpo
        else:
            caminho = os.path.join(os.path.dirname(assets),
                                   chave.split("?")[0])
            try:
                texto = io.open(caminho, encoding="utf-8", errors="replace").read()
            except Exception:
                texto = ""
        if len(texto.strip()) < minimo:
            continue                       # curto demais para fazer mal
        vistos.add(chave)
        itens.append({"id": chave, "origem": origem, "texto": texto})
    return itens


def traduzir_termos(termos, origem, destino, lote=40, quieto=False):
    """Traduz uma lista de termos chamando o CLI do Claude (`claude -p`).

    Em lotes: um pedido único com 150 frases volta truncado ou com chave
    faltando. Cada lote é conferido chave a chave e o que não voltou entra
    numa segunda tentativa; o que ainda faltar fica sem tradução (o widget
    mostra o original) em vez de virar texto inventado.
    """
    import subprocess
    if not termos:
        return {}
    alvo_nome = IDIOMAS_NOME.get(destino) or "código BCP-47 %s" % destino
    orig_nome = IDIOMAS_NOME.get(origem) or "código BCP-47 %s" % origem
    saida = {}

    def pedir(chaves):
        pedido = json.dumps({k: "" for k in chaves}, ensure_ascii=False)
        prompt = (
            "Você é tradutor de landing page publicitária.\n"
            "Traduza de %s (%s) para %s (%s).\n\n"
            "REGRAS\n"
            "- Responda SÓ com um objeto JSON, sem cercas de código, sem comentários.\n"
            "- Mesmas chaves, exatamente como vieram. Só os valores mudam.\n"
            "- Mantenha nomes de marca, nomes de pessoa, endereços, códigos e "
            "números como estão.\n"
            "- Preserve pontuação de borda, aspas soltas e espaços do começo/fim: "
            "muitas frases são pedaços de uma sentença maior.\n"
            "- Mantenha o tom comercial e o comprimento parecido — o texto entra "
            "num layout pronto.\n"
            "- Se um valor não fizer sentido traduzir, repita o original.\n"
            "- Escreva na escrita nativa do idioma de destino, não em "
            "transliteração.\n\n"
            "%s" % (origem, orig_nome, destino, alvo_nome, pedido))
        try:
            r = subprocess.run(["claude", "-p", prompt], capture_output=True,
                               text=True, timeout=600, stdin=subprocess.DEVNULL)
        except Exception as e:
            print("      erro ao chamar o claude: %s" % e)
            return {}
        txt = (r.stdout or "").strip()
        if "```" in txt:
            txt = re.sub(r"^.*?```(?:json)?\s*|\s*```.*$", "", txt, flags=re.S)
        i, f = txt.find("{"), txt.rfind("}")
        if i < 0 or f < i:
            return {}
        try:
            m = json.loads(txt[i:f + 1])
        except Exception:
            return {}
        return {k: v for k, v in m.items()
                if k in chaves and isinstance(v, str) and v.strip()}

    blocos = [termos[i:i + lote] for i in range(0, len(termos), lote)]
    for n, bloco in enumerate(blocos, 1):
        got = pedir(bloco)
        faltam = [k for k in bloco if k not in got]
        if faltam:
            got.update(pedir(faltam))
            faltam = [k for k in bloco if k not in got]
        saida.update(got)
        if not quieto:
            print("      %s lote %d/%d: %d/%d%s"
                  % (destino, n, len(blocos), len(got), len(bloco),
                     "  (%d sem tradução)" % len(faltam) if faltam else ""))
    return saida


# Acima disto, os dicionários deixam de vir embutidos e passam a ser
# buscados no clique. Abaixo, embutir é mais simples e mais rápido: um
# idioma de landing típica dá ~6 KB gzip, menos que um ícone.
LIMITE_EMBUTIDO = 120 * 1024


def escrever_i18n(pasta, base, dicionarios, codigos):
    """Grava i18n/dicionarios.js.

    É .js e não .json de propósito: em file:// um fetch de .json morre em
    CORS, e o CLAUDE.md manda conferir o clone abrindo o arquivo direto.
    """
    os.makedirs(pasta, exist_ok=True)
    nomes = {c: IDIOMAS_NOME.get(c, c.upper()) for c in codigos}
    dic = {c: dicionarios[c] for c in codigos if c != base and dicionarios.get(c)}
    cabeca = {"padrao": codigos[0], "base": base, "codigos": codigos,
              "nomes": nomes, "rtl": sorted(c for c in codigos if eh_rtl(c))}

    def dump(o):
        return json.dumps(o, ensure_ascii=False, indent=1, sort_keys=True)

    peso = sum(len(dump(d).encode("utf-8")) for d in dic.values())
    embutido = peso <= LIMITE_EMBUTIDO

    # limpa os d-*.js de uma rodada anterior que tenha usado o outro modo
    for fn in os.listdir(pasta):
        if fn.startswith("d-") and fn.endswith(".js"):
            os.remove(os.path.join(pasta, fn))

    if embutido:
        cabeca["dic"] = dic
    else:
        cabeca["dic"] = {}
        cabeca["lazy"] = {c: "i18n/d-%s.js" % c for c in dic}
        for c, d in dic.items():
            io.open(os.path.join(pasta, "d-%s.js" % c), "w", encoding="utf-8").write(
                "window.__CLONE_I18N_ADD(%s,%s);\n" % (json.dumps(c), dump(d)))

    js = ("/* gerado pelo clonar.py — dicionários de tradução do clone.\n"
          "   Editável à mão: chave = texto original, valor = tradução. */\n"
          "window.__CLONE_I18N = " + dump(cabeca) + ";\n"
          "window.__CLONE_I18N_ADD=function(c,d){\n"
          " window.__CLONE_I18N.dic[c]=d;\n"
          " if(window.__CLONE_I18N_PRONTO)window.__CLONE_I18N_PRONTO(c);\n"
          "};\n")
    io.open(os.path.join(pasta, "dicionarios.js"), "w", encoding="utf-8").write(js)
    return len(js), peso, embutido


def marcar_idiomas(html, codigos):
    """Põe data-clone-lang nas opções do seletor.

    A marca faz três coisas: o --link deixa de sequestrar o clique, o hover
    passa a mostrar o arquivo local, e o atalho de idioma sabe para onde ir.
    """
    n = [0]
    ATRIB = r'(?:data-value|data-lang|data-language|data-locale|hreflang)'

    # Se a página tem um seletor nativo, ele traz vários códigos de idioma
    # juntos. Nesse caso marcamos todos os conhecidos, mesmo os sem
    # dicionário: assim o clique fica inerte em vez de virar clique na
    # oferta. Um data-value solto (3 códigos é o piso) não conta.
    achados = {m.group(1).strip().lower() for m in re.finditer(
        r'\b' + ATRIB + r'="([^"]*)"', html)}
    if len(achados & set(IDIOMAS_NOME)) >= 3:
        codigos = set(codigos) | (achados & set(IDIOMAS_NOME))

    def marca(m):
        tag, c = m.group(0), m.group(1).strip().lower()
        if c not in codigos or "data-clone-lang" in tag:
            return tag
        n[0] += 1
        fecha = "/>" if tag.endswith("/>") else ">"
        return tag[:-len(fecha)].rstrip() + ' data-clone-lang="%s"' % c + fecha

    html = re.sub(r'<(?!/)[a-zA-Z][^>]*\b' + ATRIB + r'="([^"]*)"[^>]*>', marca, html)
    return html, n[0]


_I18N_JS = r"""
(function(){
var CFG=window.__CLONE_I18N||{dic:{},nomes:{}};
var DIC=CFG.dic||{}, NOMES=CFG.nomes||{}, BASE=CFG.base||"";
var RTL=CFG.rtl||[], DIR0=document.documentElement.getAttribute("dir")||"";
var CODIGOS=CFG.codigos||[];
function temIdioma(c){return c===BASE||CODIGOS.indexOf(c)>=0||!!DIC[c];}
var CHAVE="clone-i18n";

/* ── o que dá para traduzir na tela ───────────────────────────── */
var nos=[],orig=[],ats=[],aorig=[],tit=document.title.trim(),atual=BASE;
var MUDO=/^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE|SVG|CODE|PRE)$/;

function coletar(){
  nos=[];orig=[];ats=[];aorig=[];
  if(!document.body)return;
  var w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT,null,false),n;
  while((n=w.nextNode())){
    var p=n.parentNode;
    if(!p||MUDO.test(p.nodeName)||!n.nodeValue.trim())continue;
    /* o rótulo de cada opção do seletor já está no idioma dele */
    if(p.closest&&p.closest("[data-clone-lang]"))continue;
    nos.push(n);orig.push(n.nodeValue);
  }
  var A=["alt","title","placeholder","aria-label"];
  var els=document.body.querySelectorAll("[alt],[title],[placeholder],[aria-label]");
  for(var i=0;i<els.length;i++){
    if(els[i].closest("[data-clone-lang]"))continue;
    for(var j=0;j<A.length;j++){
      var v=els[i].getAttribute(A[j]);
      if(v&&v.trim()){ats.push([els[i],A[j]]);aorig.push(v);}
    }
  }
}

/* Nome do idioma pelo próprio navegador: serve para qualquer sigla. */
var cacheNome={};
function nome(c){
  if(cacheNome[c])return cacheNome[c];
  var n="";
  try{ n=new Intl.DisplayNames([c],{type:"language"}).of(c)||""; }catch(_){}
  if(!n||n.toLowerCase()===c.toLowerCase())n=NOMES[c]||"";
  if(!n)n=c.toUpperCase();
  if(n[0]&&n[0].toLowerCase()===n[0])n=n[0].toLocaleUpperCase(c)+n.slice(1);
  return (cacheNome[c]=n);
}

/* Dicionário grande não vem embutido: chega no clique, por <script src>
   — que funciona até em file://, onde um fetch de .json morre em CORS. */
var baixando={};
function comDicionario(cod,pronto){
  if(cod===BASE||DIC[cod]||!(CFG.lazy&&CFG.lazy[cod])){pronto();return;}
  if(baixando[cod]){baixando[cod].push(pronto);return;}
  baixando[cod]=[pronto];
  window.__CLONE_I18N_PRONTO=function(c){
    var f=baixando[c]||[];baixando[c]=null;
    for(var i=0;i<f.length;i++)f[i]();
  };
  var e=document.createElement("script");
  e.src=CFG.lazy[cod];
  e.onerror=function(){var f=baixando[cod]||[];baixando[cod]=null;
                       for(var i=0;i<f.length;i++)f[i]();};
  document.head.appendChild(e);
}

function aplicar(cod,silencioso){
  comDicionario(cod,function(){aplicarJa(cod,silencioso);});
}
/* Sempre parte do ORIGINAL guardado, nunca do texto já trocado: assim
   trocar de idioma dez vezes dá no mesmo que trocar uma. */
function aplicarJa(cod,silencioso){
  var d=DIC[cod]||null,i,o,k,t;
  for(i=0;i<nos.length;i++){
    o=orig[i];k=o.trim();t=d&&d[k];
    nos[i].nodeValue=t?o.replace(k,t):o;
  }
  for(i=0;i<ats.length;i++){
    o=aorig[i];k=o.trim();t=d&&d[k];
    ats[i][0].setAttribute(ats[i][1],t?o.replace(k,t):o);
  }
  document.title=(d&&d[tit])||tit;
  document.documentElement.setAttribute("lang",cod);
  if(RTL.indexOf(cod.split("-")[0])>=0)
    document.documentElement.setAttribute("dir","rtl");
  else if(DIR0)document.documentElement.setAttribute("dir",DIR0);
  else document.documentElement.removeAttribute("dir");
  atual=cod;
  if(!silencioso){try{localStorage.setItem(CHAVE,cod);}catch(_){}}
  /* o seletor da própria página mostra a escolha */
  var op=document.querySelectorAll("[data-clone-lang]");
  for(i=0;i<op.length;i++){
    var c=op[i].getAttribute("data-clone-lang");
    if(op[i].classList)op[i].classList[c===cod?"add":"remove"]("active");
    if(op[i].tagName==="OPTION")op[i].selected=(c===cod);
  }
  var rot=document.querySelectorAll(
    ".default-lang,.current-lang,.selected-lang,[data-lang-atual]");
  for(i=0;i<rot.length;i++)
    if(!rot[i].closest("[data-clone-lang]"))rot[i].textContent=nome(cod);
}

/* O CONTROLE é o seletor que a página já tem. Captura, e antes do snippet
   de --link, senão o clique em "English" viraria clique na oferta. */
function codigoDe(el){
  while(el&&el!==document.documentElement){
    if(el.getAttribute&&el.hasAttribute("data-clone-lang"))
      return el.getAttribute("data-clone-lang");
    el=el.parentElement;
  }
  return null;
}
document.addEventListener("click",function(e){
  var c=codigoDe(e.target);
  if(c===null)return;
  e.preventDefault();e.stopPropagation();
  if(e.stopImmediatePropagation)e.stopImmediatePropagation();
  if(temIdioma(c))aplicar(c);
},true);
/* seletor em <select>: troca não vem por clique */
document.addEventListener("change",function(e){
  var el=e.target;
  if(!el||el.tagName!=="SELECT")return;
  var o=el.options&&el.options[el.selectedIndex];
  var c=o&&o.getAttribute&&o.getAttribute("data-clone-lang");
  if(!c)return;
  e.preventDefault();e.stopPropagation();
  if(e.stopImmediatePropagation)e.stopImmediatePropagation();
  if(temIdioma(c))aplicar(c);
},true);

function iniciar(){
  coletar();
  var esc=null;
  try{esc=localStorage.getItem(CHAVE);}catch(_){}
  aplicar(esc&&temIdioma(esc)?esc:BASE,true);
}
if(document.readyState==="loading")
  document.addEventListener("DOMContentLoaded",iniciar);
else iniciar();
})();
"""


def i18n_snippet():
    return '<script data-clone="i18n">' + _I18N_JS + "</script>"


def link_snippet(dest, sem_ancoras=False):
    """Manda TODA navegação para o destino, sem quebrar a UI.

    A separação que importa: um <a> é um link — sai da página, então vai
    para a oferta, esteja dentro de um .menu ou não. O que NÃO é <a>
    (button, div com onclick) passa pelo filtro de interface, porque aí
    sim é onde vivem accordion, slider, aba, som e afins.

    Fica de fora só: âncora que aponta para um id existente (rolagem na
    própria página, accordion do Bootstrap), o seletor de idioma e as
    peças que o clonador injetou.
    """
    d = dest.replace("\\", "\\\\").replace('"', '\\"')
    # âncora viva = aponta para um id que existe. "#" e "javascript:" não
    # são âncoras: são placeholder de botão que navega por JS — era por
    # onde os CTAs escapavam mudos.
    viva_js = ('function viva(a){return false;}\n' if sem_ancoras else
               'function viva(a){var h=a.getAttribute("href")||"";'
               'if(h.charAt(0)!=="#"||h.length<2)return false;'
               'var id=h.slice(1);'
               'try{if(document.getElementById(id))return true;}catch(_){}'
               'try{if(document.getElementsByName(id).length)return true;}catch(_){}'
               'return false;}\n')
    return (
        '<script data-clone="link">\n'
        '(function(){var DEST="' + d + '";\n'
        # classes/ids de interface — só valem para o que NÃO é <a>
        'var UI=/faq|accordion|collaps|toggle|question|answer|swiper|splide|'
        'slider|carousel|\\btabs?\\b|dropdown|hamburger|modal|popup|'
        'lightbox|tooltip|counter|countdown|timer|sound|mute|volume|play|pause|'
        'zoom|thumb|gallery|lang|idioma|locale|switcher/i;\n'
        'function cls(el){if(!el||el.className==null)return "";'
        'var c=el.className;return (c.baseVal!==undefined?c.baseVal:c)+"";}\n'
        'function ui(el){while(el&&el!==document.documentElement){'
        'if(UI.test(cls(el)))return true;if(el.getAttribute){'
        'if(UI.test(el.getAttribute("id")||""))return true;'
        'var r=el.getAttribute("role")||"";'
        'if(/tab|menuitem|switch/.test(r))return true;}'
        'el=el.parentElement;}return false;}\n'
        + viva_js
        + 'function nosso(el){return el.getAttribute&&('
        'el.hasAttribute("data-clone-lang")||el.hasAttribute("data-clone-ui"));}\n'
        '["nextPage","goToCheckout","goToOrder","redirectToCheckout","toCheckout",'
        '"gotoCheckout","comprar","checkout","order"].forEach(function(f){'
        'try{window[f]=function(){location.href=DEST;};}catch(_){}});\n'
        # o href visível (hover) também aponta para a oferta
        'function fix(){var as=document.querySelectorAll("a");'
        'for(var i=0;i<as.length;i++){var a=as[i];'
        'if(nosso(a)||a.closest("[data-clone-lang],[data-clone-ui]"))continue;'
        'if(viva(a))continue;'
        'a.setAttribute("href",DEST);a.removeAttribute("target");'
        'a.removeAttribute("onclick");}}\n'
        'fix();document.addEventListener("DOMContentLoaded",fix);\n'
        'function go(e){e.preventDefault();e.stopPropagation();'
        'if(e.stopImmediatePropagation)e.stopImmediatePropagation();'
        'location.href=DEST;}\n'
        'document.addEventListener("click",function(e){'
        'var el=e.target,alvo=null,ehA=false;'
        'while(el&&el!==document.documentElement){'
        'if(nosso(el))return;'                       # nosso widget/idioma
        'var t=el.tagName?el.tagName.toLowerCase():"";'
        'if(t==="a"){if(viva(el))return;alvo=el;ehA=true;break;}'
        'if(t==="button"){if((el.getAttribute("type")||"").toLowerCase()!=="reset")'
        '{alvo=el;break;}}'
        'if(t==="input"){var y=(el.type||"").toLowerCase();'
        'if(y==="submit"||y==="button"||y==="image"){alvo=el;break;}}'
        'if(el.getAttribute&&el.hasAttribute("onclick")){alvo=el;break;}'
        'el=el.parentElement;}\n'
        'if(!alvo)return;'
        'if(!ehA&&ui(alvo))return;'                  # filtro de UI só p/ não-<a>
        'go(e);},true);\n'
        'document.addEventListener("submit",function(e){'
        'if(e.target&&e.target.closest&&e.target.closest("[data-clone-ui]"))return;'
        'go(e);},true);\n'
        '})();\n</script>')


MIME_EXT = {
    "text/css": ".css", "application/javascript": ".js", "text/javascript": ".js",
    "image/webp": ".webp", "image/png": ".png", "image/jpeg": ".jpg",
    "image/svg+xml": ".svg", "image/gif": ".gif", "image/avif": ".avif",
    "video/webm": ".webm", "video/mp4": ".mp4", "font/woff2": ".woff2",
    "font/woff": ".woff", "application/json": ".json",
}


def eh_tracker(url):
    """Decide pela URL de ORIGEM, na ordem: domínio de tracking > UI > padrão."""
    u = url.lower()
    if any(t in u for t in TRACKER_DOMINIOS):
        return True
    if any(t in u for t in UI_KEEP):
        return False
    return any(t in u for t in TRACKER_SRC)


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
    rel = sp.path.lstrip("/")               # forma relativa sem barra inicial
    for v in (url,
              sp.scheme + "://" + sp.netloc + sp.path + q,
              sp.scheme + "://" + sp.netloc + sp.path,
              "//" + sp.netloc + sp.path + q,
              "//" + sp.netloc + sp.path,
              sp.path + q,
              sp.path,
              # caminhos relativos (o HTML usa "assets/ja/css/x.css",
              # "./assets/ja/images/y.png", "../common/css/z.css" — sem
              # domínio nem barra inicial, às vezes subindo de nível)
              rel + q,
              rel,
              "./" + rel + q,
              "./" + rel,
              "../" + rel,
              "../../" + rel):
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
                marcar=False, redirect="", so_frontend=False, link="",
                sem_ancoras=False,
                sem_idiomas=False,
                idioma_origem="", sem_traduzir=False, sem_triagem=False,
                permitir_externos=False):
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

    sit, motivo = diagnostica_pagina(
        html, d.get("title", ""), None, len(files))
    if sit != "ok":
        sys.exit(
            "ERRO: a captura não é a página — é %s (%r).\n"
            "      Título capturado: %r\n"
            "      Clonar isso empacotaria a tela de erro no lugar do site.\n"
            "      %s"
            % ("um bloqueio" if sit == "bloqueado" else "um desafio",
               motivo, d.get("title", ""),
               "Bloqueio é a rede recusando seu IP: use VPN ou --proxy."
               if sit == "bloqueado" else
               "Desafio costuma passar com --visivel (resolva uma vez; "
               "o cookie fica salvo)."))

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

    # As duas etapas pesadas viram função para poder rodar também nas
    # páginas de idioma (index-en.html, index-es.html…), que passam pelo
    # mesmíssimo tratamento — sem duplicar a lógica de limpeza.
    def diga(*x):
        if not quieto[0]:
            print(*x)
    quieto = [False]

    def relocalizar(html):
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

        # cache-buster: o HTML costuma referenciar "x.png?t=123456" enquanto o
        # asset foi capturado/gravado sem essa query. Casa o caminho seguido de
        # qualquer "?..." e troca pelo arquivo local.
        n_cb = 0
        for url, local in sorted(url2local.items(), key=lambda kv: -len(kv[0])):
            sp2 = urlsplit(url)
            rel2 = sp2.path.lstrip("/")
            for base in dict.fromkeys([sp2.path, rel2, "./" + rel2, "../" + rel2]):
                if len(base) < 2:
                    continue
                pat = r'(?<=["\'(,\s])' + re.escape(base) + r'\?[^"\')\s,]*'
                html, k = re.subn(pat, local.replace("\\", "\\\\"), html)
                n_cb += k
        n += n_cb

            # ── referências relativas, resolvidas contra a URL da página ──
        # Gerar variantes de cada asset não alcança uma página que mora num
        # subdiretório: em /smartring/en/us/int2 o HTML escreve
        # "css/reset.css" e "../../../../css/x.css", formas que nenhuma
        # variante prevê. Resolver a referência contra a URL da página, sim
        # — e é exato, não chute. Sem isto o clone vinha só com o HTML.
        por_abs = dict(url2local)
        por_sem_q = {}
        por_base = {}
        for u, l in url2local.items():
            por_sem_q.setdefault(u.split("?")[0], l)
            por_base.setdefault(unquote(os.path.basename(urlsplit(u).path)), l)

        def acha_local(u):
            try:
                a = urljoin(page_url, u)
            except Exception:
                return None
            if urlsplit(a).netloc != urlsplit(page_url).netloc:
                return None
            return (por_abs.get(a) or por_sem_q.get(a.split("?")[0])
                    or por_base.get(unquote(os.path.basename(
                        urlsplit(a).path))))

        n_rel = [0]

        def troca_ref(m):
            pre, u, pos = m.group(1), m.group(2), m.group(3)
            if not u or u.startswith(("http://", "https://", "//", "data:",
                                      "#", "javascript:", "mailto:", "tel:",
                                      "assets/", "\x00")):
                return m.group(0)
            l = acha_local(u)
            if not l:
                return m.group(0)
            n_rel[0] += 1
            return pre + l + pos

        html = re.sub(
            r'((?:src|href|poster|data-src|data-lazy-src|data-original)\s*=\s*")'
            r'([^"]*)(")', troca_ref, html)

        def troca_srcset(m):
            partes = []
            for parte in m.group(2).split(","):
                p = parte.strip().split()
                if not p:
                    continue
                l = acha_local(p[0]) if not p[0].startswith(
                    ("http", "//", "data:", "assets/", "\x00")) else None
                if l:
                    n_rel[0] += 1
                    p[0] = l
                partes.append(" ".join(p))
            return m.group(1) + ", ".join(partes) + m.group(3)

        html = re.sub(r'((?:srcset|data-srcset)\s*=\s*")([^"]*)(")',
                      troca_srcset, html)

        def troca_url_css(m):
            u = m.group(1).strip("'\" ")
            if u.startswith(("http", "//", "data:", "assets/", "\x00")):
                return m.group(0)
            l = acha_local(u)
            if not l:
                return m.group(0)
            n_rel[0] += 1
            return "url(" + l + ")"

        html = re.sub(r"url\(([^)]+)\)", troca_url_css, html)
        if n_rel[0]:
            n += n_rel[0]
            diga("refs relativas resolvidas contra a URL da página: %d" % n_rel[0])

        # âncoras que apontam para a própria página
        base_page = page_url.split("#")[0]
        html, k = re.subn(re.escape(base_page) + r"#", "#", html)
        n += k
        diga("URLs reescritas no HTML: %d%s" % (n, " (%d com cache-buster)" % n_cb if n_cb else ""))

        return html

    # Um script de tracker já teve o src reescrito para assets/xxx.js, então
    # "mxj5trk" some do src. Este mapa recupera a URL de origem para a
    # marcação decidir pelo domínio real, não pelo nome local.
    local2url = {v.split("?")[0]: k for k, v in url2local.items()}

    triagem = {}          # preenchido pela triagem antes de montar()

    def montar(html):
        # Comentário HTML sai INTEIRO do clone, sempre. Dois motivos:
        # não serve para nada num clone, e um <script> comentado quebra o
        # pareamento do regex — o </script> de dentro do comentário fecha o
        # par errado e o tracker REAL logo depois vira "corpo" do casamento
        # anterior, escapando da limpeza. Foi assim que o gtag da Melara Max
        # passou. Mascarar aqui e descartar no fim resolve os dois.
        n_com = [0]

        def _guarda(m):
            n_com[0] += 1
            return "\x00COM\x00"

        html = re.sub(r"<!--.*?-->", _guarda, html, flags=re.S)

        def _devolve(h):
            h = h.replace("\x00COM\x00", "")
            h = re.sub(r"<!--.*?-->", "", h, flags=re.S)   # os que nós criamos
            if n_com[0]:
                diga("comentários HTML removidos: %d" % n_com[0])
            return h

        mortos = []
        if not a.manter_trackers:
            def mata(m):
                attrs, corpo = m.group(1), m.group(2)
                if "data-clone-disabled" in attrs:
                    return m.group(0)
                porque, chave, _ = regra_script(attrs, corpo, local2url)
                if not porque and chave:
                    # as listas não sabiam: vale o que a triagem decidiu
                    v = triagem.get(chave) or {}
                    if v.get("classe") == "rastreamento":
                        porque = "triagem: " + (v.get("porque") or "rastreamento")
                if not porque:
                    return m.group(0)
                mortos.append(porque)
                return ('<script type="text/plain" data-clone-disabled="%s"%s>%s</script>'
                        % (porque, attrs, corpo))

            html = re.sub(r"<script\b([^>]*)>(.*?)</script>", mata, html, flags=re.S)

            # Guarda o JS dos dois lados ANTES de apagar: é a única janela em
            # que dá para saber quais globais saíram com os rastreadores.
            def _junta(removidos):
                pedacos = []
                for mm in re.finditer(r"<script\b([^>]*)>(.*?)</script>", html, re.S):
                    at, cp = mm.group(1), mm.group(2)
                    if ("data-clone-disabled" in at) != removidos:
                        continue
                    if "data-clone=" in at:
                        continue                  # snippets nossos não contam
                    sc = re.search(r'src="([^"]*)"', at)
                    if sc:
                        cam = os.path.join(out, sc.group(1).split("?")[0])
                        try:
                            cp = io.open(cam, encoding="utf-8", errors="replace").read()
                        except Exception:
                            cp = ""
                    pedacos.append(cp)
                return "\n".join(pedacos)

            js_saiu, js_fica = _junta(True), _junta(False)
            html, n_ns = re.subn(r"<noscript><iframe[^>]*(?:googletagmanager|facebook)[^>]*>.*?</noscript>",
                                 "", html, flags=re.S)

            # pixels são <img>/<iframe>, não <script>: bloquear só o download
            # deixaria a tag apontando para o rastreador e ela dispararia igual.
            px = [0]

            def minusculo(attrs):
                """1x1 invisível não é interface — é beacon, venha de onde vier."""
                def dim(nome):
                    m = re.search(r'\b%s="(\d+)' % nome, attrs) or \
                        re.search(r'%s\s*:\s*(\d+)\s*px' % nome, attrs)
                    return int(m.group(1)) if m else None
                l, a = dim("width"), dim("height")
                return l is not None and a is not None and l <= 2 and a <= 2

            def mata_pixel(m):
                tag, attrs = m.group(1), m.group(2)
                src = re.search(r'src="([^"]*)"', attrs)
                # o src já virou "assets/xxx": a decisão olha a URL de ORIGEM.
                alvo_src = src.group(1) if src else ""
                origem = local2url.get(alvo_src.split("?")[0], alvo_src)
                porque = None
                if src and (eh_tracker(origem) or "saved_resource" in alvo_src):
                    porque = "pixel"
                elif tag == "iframe" and minusculo(attrs):
                    porque = "iframe-1x1"          # inclusive sem src / about:blank
                elif tag == "img" and src and minusculo(attrs) and eh_tracker(origem):
                    porque = "pixel-1x1"
                if not porque:
                    return m.group(0)
                limpo = re.sub(r'\ssrc="[^"]*"', "", attrs)
                px[0] += 1
                return '<%s%s data-clone-disabled="%s">' % (tag, limpo, porque)

            html = re.sub(r"<(img|iframe)([^>]*)>", mata_pixel, html)
            diga("rastreadores encontrados: %d scripts, %d noscript, %d pixels/iframes"
                  % (len(mortos), n_ns, px[0]))

            if not a.marcar:
                # LIMPEZA TOTAL: tira o que foi marcado em vez de só desativar,
                # e mais tudo que amarra a página ao servidor de origem.
                c = {}
                html, c["scripts"] = re.subn(
                    r"<script\b[^>]*data-clone-disabled[^>]*>.*?</script>\s*", "", html, flags=re.S)
                html, c["iframes"] = re.subn(
                    r"<iframe\b[^>]*data-clone-disabled[^>]*>.*?</iframe>\s*", "", html, flags=re.S)
                html, c["pixels"] = re.subn(
                    r"<(?:img|iframe)\b[^>]*data-clone-disabled[^>]*>\s*(?:</iframe>\s*)?", "", html)
                html, c["noscript"] = re.subn(
                    r"<noscript>\s*(?:<!--[^>]*-->)?\s*</noscript>\s*", "", html)
                # preconnect/dns-prefetch: só abrem conexão, nunca renderizam nada
                html, c["hints"] = re.subn(
                    r'<link\b[^>]*rel="(?:preconnect|dns-prefetch)"[^>]*>\s*', "", html)
                html, c["hints2"] = re.subn(
                    r'<link\b(?=[^>]*rel="(?:preconnect|dns-prefetch)")[^>]*>\s*', "", html)
                # preload/prefetch que ainda apontam para fora
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
                    extra, orfaos = stubs_orfaos(js_fica, js_saiu)
                    if orfaos:
                        diga("stubs para globais órfãos: %s"
                             % ", ".join("%s(%d métodos)" % (n, len(ms))
                                         for n, ms in sorted(orfaos.items())))
                    html = re.sub(r"(<head\b[^>]*>)",
                                  lambda m: m.group(1) + STUBS + extra, html, count=1)
                diga("LIMPEZA: %s" % ", ".join("%s=%d" % (k, v) for k, v in c.items() if v))

        if link:
            # Padrão: TODA navegação (troca de página, link externo, botão de
            # checkout, submit de formulário) vai para o link fornecido. O que
            # permanece na página — âncoras internas (#) e interações de UI
            # (FAQ, slider, menu) — não é tocado.
            alvo = link.replace("\\", "\\\\").replace('"', "&quot;")

            # (1) Reescrita estática do href dos <a> que trocam de página / são
            #     externos (mantém âncoras internas), para o hover mostrar o link.
            # Numa pre-sell, TODA saída vai para a oferta. Só fica quem
            # não sai: âncora que aponta para um id que existe na página
            # (rolagem, accordion do Bootstrap) e o seletor de idioma.
            # "javascript:void(0)" e "#" pelado NÃO são âncoras — são o
            # placeholder clássico de botão que navega por JS, e era por
            # onde os CTAs escapavam mudos.
            ids = set(re.findall(r'\bid="([^"]+)"', html))
            ids |= set(re.findall(r'\bname="([^"]+)"', html))

            def ancora_viva(h):
                if sem_ancoras:
                    return False          # nem rolagem interna sobrevive
                return len(h) > 1 and h.startswith("#") and h[1:] in ids

            def troca_a(m):
                tag = m.group(0)
                if "data-clone-lang" in tag or "data-clone-ui" in tag:
                    return tag           # seletor de idioma / peça nossa
                h = re.search(r'href="([^"]*)"', tag)
                if h and ancora_viva(h.group(1)):
                    return tag                       # rolagem na própria página
                if h:
                    tag = re.sub(r'href="[^"]*"', 'href="%s"' % alvo, tag, count=1)
                else:
                    tag = tag[:2] + ' href="%s"' % alvo + tag[2:]
                tag = re.sub(r'\son\w+="[^"]*"', "", tag)
                tag = re.sub(r'\starget="[^"]*"', "", tag)
                return tag

            html, n_link = re.subn(r"<a\b[^>]*>", troca_a, html)
            diga("LINK nos <a>: %d -> %s" % (n_link, link))

            # (2) Snippet: sobrescreve funções de troca de página, intercepta
            #     cliques que levam a outra página e o submit de formulários.
            html = html.replace("</body>", link_snippet(link, sem_ancoras) + "\n</body>", 1) \
                if "</body>" in html else html + link_snippet(link, sem_ancoras)

        if redirect:
            # depois da limpeza: entra no fim do <body> para rodar por último
            snip = redirect_snippet(redirect)
            if "</body>" in html:
                html = html.replace("</body>", snip + "\n</body>", 1)
            else:
                html += snip
            diga("REDIRECT: todo clique -> %s" % redirect)
        if not a.manter_trackers and not permitir_externos:
            html, cx, doms = neutraliza_externos(html)
            if cx:
                diga("chamadas externas cortadas: %s  [%s]"
                     % (", ".join("%s=%d" % kv for kv in sorted(cx.items())),
                        ", ".join(doms[:6]) + ("…" if len(doms) > 6 else "")))
        return _devolve(html)

    html = relocalizar(html)

    # ── 3b. idiomas ───────────────────────────────────────────────
    # Regra: o clone oferece EXATAMENTE os idiomas que a página oferecia, e
    # quem controla a troca é o seletor que ela já tem. Página sem seletor
    # não ganha sistema de idioma nenhum — nada de botão injetado, nada de
    # tradução para idioma que o site não tinha.
    #
    # A troca passa a ser na hora, sem recarregar: o seletor original
    # mandava para ?lang=xx, que num clone estático só devolveria a mesma
    # página. Aqui ele passa a reescrever o texto pelo dicionário.
    vindos = {k.lower(): v for k, v in (d.get("idiomas") or {}).items()}
    if idioma_origem:
        base_lang = normaliza_codigo(idioma_origem)
        if not base_lang:
            sys.exit("ERRO: --idioma-origem inválido: %s" % idioma_origem)
        origem_de = "informado no comando"
    else:
        base_lang, origem_de = idioma_da_pagina(html)
        if not base_lang:
            base_lang, origem_de = idioma_da_pagina(
                html, amostra=sorted(set(segmentos(html).textos)))
        if not base_lang:
            sys.exit("ERRO: a página não declara idioma e não deu para "
                     "detectar.\n      Passe --idioma-origem <sigla>.")

    traduzidos = sorted(c for c, v in vindos.items()
                        if c != base_lang and v.get("html"))
    pasta_i18n = os.path.join(out, "i18n")
    dicio, fonte = {}, {}
    base_para_dic = html

    if sem_idiomas or not traduzidos:
        html = montar(html)
        if not traduzidos:
            print("idiomas: a página é só em %s (%s) — sem seletor no HTML, "
                  "nada a oferecer" % (base_lang, origem_de))
    else:
        # (1) as versões que o próprio servidor devolveu traduzidas
        for c in traduzidos:
            dic, cob = dicionario_da_variante(base_para_dic, vindos[c]["html"])
            if cob >= 0.5 and dic:
                dicio[c], fonte[c] = dic, "origem"
            else:
                print("   %-9s só %.0f%% casou com a página" % (c, cob * 100))
        # (2) dicionário à mão / cache de rodada anterior
        if os.path.isdir(pasta_i18n):
            for fn in sorted(os.listdir(pasta_i18n)):
                if not fn.endswith(".json") or fn.startswith("_"):
                    continue
                c = fn[:-5].lower()
                if c not in traduzidos:
                    continue
                try:
                    m = json.load(io.open(os.path.join(pasta_i18n, fn), encoding="utf-8"))
                except Exception as e:
                    print("   i18n/%s ilegível: %s" % (fn, e))
                    continue
                m = {k: v for k, v in (m or {}).items()
                     if isinstance(v, str) and v.strip()} if isinstance(m, dict) else {}
                if m:
                    dicio.setdefault(c, {}).update(m)
                    fonte[c] = "origem+arquivo" if fonte.get(c) == "origem" else "arquivo"

        html, n_marc = marcar_idiomas(html, set(traduzidos) | {base_lang})
        html = montar(html)
        os.makedirs(pasta_i18n, exist_ok=True)

        base = segmentos(html)
        termos = sorted(set(base.textos) | set(base.atributos) |
                        ({base.titulo} if base.titulo else set()))

        # (3) o site oferece o idioma mas o alinhamento não deu: traduz
        pendentes = [c for c in traduzidos
                     if len(dicio.get(c, {})) < len(termos) * 0.5]
        if pendentes and not sem_traduzir:
            print("traduzindo %d termos de %s para: %s"
                  % (len(termos), base_lang, ", ".join(pendentes)))
            for c in pendentes:
                falta = [t for t in termos if t not in dicio.get(c, {})]
                novo_dic = traduzir_termos(falta, base_lang, c)
                if novo_dic:
                    dicio.setdefault(c, {}).update(novo_dic)
                    fonte[c] = "traduzido" if not fonte.get(c) else fonte[c] + "+traduzido"
                    io.open(os.path.join(pasta_i18n, c + ".json"), "w",
                            encoding="utf-8").write(json.dumps(
                                dicio[c], ensure_ascii=False, indent=1, sort_keys=True))

        codigos = [base_lang] + [c for c in traduzidos if dicio.get(c)]
        n_js, peso, embutido = escrever_i18n(pasta_i18n, base_lang, dicio, codigos)

        if n_marc < 2:
            print("!! o HTML oferece %d idiomas mas não achei o seletor deles "
                  "na página." % len(traduzidos))
            print("   Sem controle, a troca não teria como acontecer — "
                  "sistema de idioma desligado.")
            codigos = [base_lang]
        else:
            snip = ('<script src="i18n/dicionarios.js"></script>\n'
                    + i18n_snippet())
            marca_link = '<script data-clone="link">'
            if marca_link in html:
                html = html.replace(marca_link, snip + "\n" + marca_link, 1)
            elif "</body>" in html:
                html = html.replace("</body>", snip + "\n</body>", 1)
            else:
                html += snip
            print("idiomas: %d do próprio site, no seletor da própria página "
                  "(%d elementos religados)" % (len(codigos), n_marc))
            print("   %-9s %4d termos (texto original, %s)"
                  % (base_lang, len(termos), origem_de))
            for c in codigos[1:]:
                print("   %-9s %4d/%d termos (%s)"
                      % (c, len(dicio[c]), len(termos), fonte.get(c, "?")))
            print("   dicionários: %.0f KB %s"
                  % (peso / 1024.0, "embutidos" if embutido
                     else "em arquivo por idioma, buscados no clique"))

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
    # Ficha do clone: quando saiu, de onde, com que link. Sem isto não dá
    # para saber se o que está no ar é o clone recém-feito ou um antigo —
    # dúvida que já custou tempo nesta bancada.
    ficha = {
        "origem": page_url,
        "quando": time.strftime("%Y-%m-%d %H:%M:%S"),
        "link_afiliado": link or "",
        "idioma_base": locals().get("base_lang", ""),
        "idiomas": locals().get("codigos", []),
        "assets": len(os.listdir(assets)) if os.path.isdir(assets) else 0,
        "faltando": len(faltando),
        "externos": sorted(vivos_fora) if "vivos_fora" in locals() else [],
        "comando": " ".join(sys.argv[1:]),
    }
    io.open(os.path.join(out, ".clone.json"), "w", encoding="utf-8").write(
        json.dumps(ficha, ensure_ascii=False, indent=1))

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
    ap.add_argument("--idioma-origem", default="", metavar="COD",
                    help="idioma em que a página capturada está "
                         "(padrão: o <html lang> dela)")
    ap.add_argument("--permitir-externos", action="store_true",
                    help="deixa a página buscar de fora o que sobrou (o padrão "
                         "é cortar: um clone não telefona para ninguém)")
    ap.add_argument("--sem-triagem", action="store_true",
                    help="não usa a LLM para julgar os scripts que as listas "
                         "não decidem (mantém todos, como antes)")
    ap.add_argument("--sem-traduzir", action="store_true",
                    help="não chama o Claude para traduzir o que faltar; usa só "
                         "o que veio da captura e os i18n/<cod>.json existentes")
    ap.add_argument("--sem-idiomas", action="store_true",
                    help="ignora os idiomas do site; entrega só o original")
    ap.add_argument("--sem-ancoras", action="store_true",
                    help="manda para o link até os <a href=\"#secao\"> que só "
                         "rolam a própria página (padrão: rolagem interna fica, "
                         "porque não tira o visitante da página)")
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
                so_frontend=a.so_frontend, link=a.link, sem_ancoras=a.sem_ancoras,
                sem_idiomas=a.sem_idiomas,
                idioma_origem=a.idioma_origem, sem_traduzir=a.sem_traduzir,
                sem_triagem=a.sem_triagem,
                permitir_externos=a.permitir_externos)


if __name__ == "__main__":
    main()
