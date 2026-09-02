#!/usr/bin/env python3
"""
CLONADOR DE PÁGINAS — passo 2 de 2: RECONSTRUÇÃO

Uso:  ./clonar.py ~/Downloads/captura-exemplo-com.json [nome-do-clone]

Lê o JSON gerado por capturar.js e monta um clone local autocontido:
grava os assets, reescreve HTML e CSS para caminhos locais, neutraliza
rastreadores e audita o resultado.
"""
import argparse, base64, hashlib, io, json, os, re, sys
from html.parser import HTMLParser
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
IGNORA_TEXTO = {"script", "style", "noscript", "template", "svg", "code", "pre"}
ATRIB_TEXTO = ("alt", "title", "placeholder", "aria-label")


class _Segmentos(HTMLParser):
    """Coleta o texto traduzível de um HTML, na ordem do documento.

    Ordem importa: é ela que alinha a página original com a versão que o
    servidor devolveu traduzida, já que as duas saem do mesmo template.
    """

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.mudo = []
        self.textos = []
        self.atributos = []
        self.titulo = ""
        self._em_titulo = False

    def handle_starttag(self, tag, attrs):
        # "English", "日本語" e afins são rótulos do seletor: cada um já está
        # no próprio idioma e traduzi-los seria o oposto do que se quer.
        rotulo = any(k in ("data-value", "data-lang", "data-language",
                           "data-locale", "hreflang", "data-clone-lang")
                     and (v or "").strip().lower() in IDIOMAS_NOME
                     for k, v in attrs)
        if tag in IGNORA_TEXTO or rotulo:
            self.mudo.append(tag)
        if tag == "title":
            self._em_titulo = True
        if self.mudo:
            return
        for k, v in attrs:
            if k in ATRIB_TEXTO and v and v.strip() and _traduzivel(v):
                self.atributos.append(v.strip())

    def handle_endtag(self, tag):
        if self.mudo and self.mudo[-1] == tag:
            self.mudo.pop()
        if tag == "title":
            self._em_titulo = False

    def handle_data(self, dado):
        if self._em_titulo:
            self.titulo = dado.strip()
            return
        if self.mudo:
            return
        t = dado.strip()
        if t and _traduzivel(t):
            self.textos.append(t)


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
    """Casa a página original com a versão traduzida pelo servidor.

    As duas vêm do mesmo template, então o texto sai na mesma ordem e o
    pareamento é posicional. Se as contagens divergem, a variante não é o
    mesmo template — devolve vazio em vez de inventar um alinhamento torto.
    """
    b, v = segmentos(html_base), segmentos(html_var)
    if len(b.textos) != len(v.textos) or len(b.atributos) != len(v.atributos):
        return None, (len(b.textos), len(v.textos))
    d = {}
    for o, t in list(zip(b.textos, v.textos)) + list(zip(b.atributos, v.atributos)):
        if o != t and t:
            d.setdefault(o, t)
    if b.titulo and v.titulo and b.titulo != v.titulo:
        d[b.titulo] = v.titulo
    return d, (len(b.textos), len(v.textos))


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
    alvo_nome = IDIOMAS_NOME.get(destino, destino)
    orig_nome = IDIOMAS_NOME.get(origem, origem)
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
            "- Se um valor não fizer sentido traduzir, repita o original.\n\n"
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


def escrever_i18n(pasta, base, dicionarios, codigos):
    """Grava i18n/dicionarios.js.

    É .js e não .json de propósito: em file:// um fetch de .json morre em
    CORS, e o CLAUDE.md manda conferir o clone abrindo o arquivo direto.
    """
    os.makedirs(pasta, exist_ok=True)
    nomes = {c: IDIOMAS_NOME.get(c, c.upper()) for c in codigos}
    corpo = {"padrao": codigos[0], "base": base, "codigos": codigos, "nomes": nomes,
             "dic": {c: dicionarios[c] for c in codigos
                     if c != base and dicionarios.get(c)}}
    js = ("/* gerado pelo clonar.py — dicionários de tradução do clone.\n"
          "   Editável à mão: chave = texto original, valor = tradução. */\n"
          "window.__CLONE_I18N = " +
          json.dumps(corpo, ensure_ascii=False, indent=1, sort_keys=True) + ";\n")
    io.open(os.path.join(pasta, "dicionarios.js"), "w", encoding="utf-8").write(js)
    return len(js)


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


CANTOS = {"bl": "left:16px;bottom:16px", "br": "right:16px;bottom:16px",
          "tl": "left:16px;top:16px", "tr": "right:16px;top:16px"}

_I18N_JS = r"""
(function(){
var CFG=window.__CLONE_I18N||{dic:{},nomes:{},padrao:"__PADRAO__"};
var DIC=CFG.dic||{}, NOMES=CFG.nomes||{}, PADRAO=CFG.padrao||"__PADRAO__";
var CHAVE="clone-i18n", AUTO=__AUTO__, BASE=CFG.base||PADRAO;
/* a ordem é a que veio em --idiomas; o padrão é o primeiro */
var codigos=(CFG.codigos&&CFG.codigos.length?CFG.codigos:Object.keys(DIC)).slice();
if(codigos.indexOf(PADRAO)<0)codigos.unshift(PADRAO);

/* ── o que dá para traduzir na tela ───────────────────────────── */
var nos=[],orig=[],ats=[],aorig=[],tit=document.title.trim(),atual=PADRAO;
var MUDO=/^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE|SVG|CODE|PRE)$/;

function nosso(el){
  while(el){ if(el.getAttribute&&el.hasAttribute("data-clone-ui"))return true;
             el=el.parentNode||el.host; }
  return false;
}
function coletar(){
  nos=[];orig=[];ats=[];aorig=[];
  if(!document.body)return;
  var w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT,null,false),n;
  while((n=w.nextNode())){
    var p=n.parentNode;
    if(!p||MUDO.test(p.nodeName)||!n.nodeValue.trim()||nosso(p))continue;
    nos.push(n);orig.push(n.nodeValue);
  }
  var A=["alt","title","placeholder","aria-label"];
  var els=document.body.querySelectorAll("[alt],[title],[placeholder],[aria-label]");
  for(var i=0;i<els.length;i++){
    if(nosso(els[i]))continue;
    for(var j=0;j<A.length;j++){
      var v=els[i].getAttribute(A[j]);
      if(v&&v.trim()){ats.push([els[i],A[j]]);aorig.push(v);}
    }
  }
}

/* Sempre parte do ORIGINAL guardado, nunca do texto já trocado: assim
   trocar de idioma dez vezes seguidas dá no mesmo que trocar uma. */
function aplicar(cod,silencioso){
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
  atual=cod;
  if(!silencioso){try{localStorage.setItem(CHAVE,cod);}catch(_){}}
  /* o seletor nativo da página, se existir, acompanha a escolha */
  var op=document.querySelectorAll("[data-clone-lang]");
  for(i=0;i<op.length;i++){
    var c=op[i].getAttribute("data-clone-lang");
    if(op[i].classList)op[i].classList[c===cod?"add":"remove"]("active");
  }
  var dl=document.querySelector(".default-lang,.current-lang,[data-lang-atual]");
  if(dl&&!nosso(dl))dl.textContent=NOMES[cod]||cod;
  pintar();
}

/* ── botão flutuante, isolado da página em Shadow DOM ──────────── */
var host,sh,pill,menu;
var ESTILO='<style>'+
':host{all:initial;display:block;position:fixed;z-index:2147483647;__CANTO__}'+
'*{box-sizing:border-box;font:500 13px/1.35 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}'+
'.pill{display:flex;align-items:center;gap:7px;padding:9px 13px;border:1px solid rgba(15,15,15,.14);'+
 'border-radius:999px;background:#fff;color:#1a1a1a;cursor:pointer;'+
 'box-shadow:0 2px 10px rgba(0,0,0,.13),0 0 0 1px rgba(255,255,255,.6);'+
 'transition:transform .12s ease,box-shadow .12s ease}'+
'.pill:hover{transform:translateY(-1px);box-shadow:0 4px 16px rgba(0,0,0,.18)}'+
'.pill svg{flex:0 0 auto}'+
'.ch{opacity:.5;font-size:10px;transition:transform .18s}'+
'.aberto .ch{transform:rotate(180deg)}'+
'.menu{position:absolute;min-width:190px;max-height:60vh;overflow:auto;padding:6px;'+
 'background:#fff;color:#1a1a1a;border:1px solid rgba(15,15,15,.14);border-radius:12px;'+
 'box-shadow:0 8px 30px rgba(0,0,0,.2);__MENUPOS__}'+
'.menu[hidden]{display:none}'+
'.cod{max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}'+
'.cur{display:none;font-weight:700;letter-spacing:.02em}'+
'@media (max-width:520px){'+
 '.pill{padding:10px 12px}'+
 '.cod{display:none}.cur{display:inline}'+
 '.menu{position:fixed;left:10px;right:10px;width:auto;min-width:0;'+
  'max-height:min(58vh,420px);__MENUMOB__}'+
 '.it{padding:12px 12px;font-size:15px}'+
'}'+
'@media (hover:none){.it{padding:13px 12px}}'+

'.it{display:flex;align-items:center;justify-content:space-between;gap:10px;width:100%;'+
 'padding:8px 10px;border:0;border-radius:8px;background:none;color:inherit;'+
 'text-align:left;cursor:pointer;font:inherit}'+
'.it:hover{background:rgba(15,15,15,.06)}'+
'.it[aria-selected="true"]{background:#e9f2ff;color:#0b63ce;font-weight:600}'+
'.tick{opacity:0}.it[aria-selected="true"] .tick{opacity:1}'+
'@media (prefers-color-scheme:dark){'+
 '.pill,.menu{background:#1f2023;color:#f0f0f0;border-color:rgba(255,255,255,.16);'+
  'box-shadow:0 2px 10px rgba(0,0,0,.5)}'+
 '.it:hover{background:rgba(255,255,255,.09)}'+
 '.it[aria-selected="true"]{background:#16324f;color:#8ab8f5}}'+
'</style>';
var GLOBO='<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" '+
 'stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a15 15 0 0 1 0 18'+
 'a15 15 0 0 1 0-18"/></svg>';

function pintar(){
  if(!sh)return;
  sh.querySelector(".cod").textContent=NOMES[atual]||atual.toUpperCase();
  sh.querySelector(".cur").textContent=atual.split("-")[0].toUpperCase();
  var its=sh.querySelectorAll(".it");
  for(var i=0;i<its.length;i++)
    its[i].setAttribute("aria-selected",its[i].dataset.cod===atual?"true":"false");
}
function abrir(v){
  if(v)menu.removeAttribute("hidden");else menu.setAttribute("hidden","");
  pill.classList[v?"add":"remove"]("aberto");
  pill.setAttribute("aria-expanded",v?"true":"false");
}
function montar(){
  if(codigos.length<2)return;              /* um idioma só: sem botão */
  host=document.createElement("div");
  host.setAttribute("data-clone-ui","i18n");
  host.setAttribute("data-clone-widget","i18n");
  host.style.cssText="position:fixed;z-index:2147483647";
  sh=host.attachShadow({mode:"open"});
  var itens="";
  for(var i=0;i<codigos.length;i++)
    itens+='<button class="it" role="option" data-cod="'+codigos[i]+'">'+
           '<span>'+(NOMES[codigos[i]]||codigos[i])+'</span><span class="tick">✓</span></button>';
  sh.innerHTML=ESTILO+
    '<button class="pill" aria-haspopup="listbox" aria-expanded="false" aria-label="Idioma">'+
    GLOBO+'<span class="cod"></span><span class="cur"></span><span class="ch">▾</span></button>'+
    '<div class="menu" role="listbox" hidden>'+itens+'</div>';
  document.body.appendChild(host);
  pill=sh.querySelector(".pill");menu=sh.querySelector(".menu");
  pill.addEventListener("click",function(e){
    e.stopPropagation();abrir(menu.hasAttribute("hidden"));});
  var its=sh.querySelectorAll(".it");
  for(var i=0;i<its.length;i++)its[i].addEventListener("click",function(e){
    e.stopPropagation();aplicar(this.dataset.cod);abrir(false);});
  document.addEventListener("click",function(){if(menu)abrir(false);});
  addEventListener("keydown",function(e){if(e.key==="Escape")abrir(false);});
}

/* Seletor nativo da página (marcado com data-clone-lang) troca o idioma
   pelo mesmo caminho. Captura, e antes do snippet de --link, senão o
   clique em "English" viraria clique na oferta. */
document.addEventListener("click",function(e){
  var el=e.target;
  while(el&&el!==document.documentElement){
    if(el.getAttribute&&el.hasAttribute("data-clone-lang")){
      var c=el.getAttribute("data-clone-lang");
      e.preventDefault();e.stopPropagation();
      if(e.stopImmediatePropagation)e.stopImmediatePropagation();
      if(DIC[c]||c===BASE)aplicar(c);
      return;
    }
    el=el.parentElement;
  }
},true);

function iniciar(){
  coletar();montar();
  var esc=null;
  try{esc=localStorage.getItem(CHAVE);}catch(_){}
  /* A 1ª visita abre no idioma padrão escolhido no comando. Só com
     --idioma-auto a página tenta adivinhar pelo idioma do navegador. */
  if(!esc&&AUTO){
    var n=(navigator.language||"").toLowerCase();
    if(DIC[n])esc=n;
    else{var b=n.split("-")[0];
         for(var i=0;i<codigos.length;i++)
           if(codigos[i]===b||codigos[i].split("-")[0]===b){esc=codigos[i];break;}}
  }
  aplicar(esc&&(DIC[esc]||esc===BASE)?esc:PADRAO,true);
}
if(document.readyState==="loading")
  document.addEventListener("DOMContentLoaded",iniciar);
else iniciar();
})();
"""


def i18n_snippet(padrao, canto="bl", auto=False):
    pos = CANTOS.get(canto, CANTOS["bl"])
    menupos = ("bottom:calc(100% + 8px);left:0" if canto[0] == "b" else
               "top:calc(100% + 8px);left:0")
    if canto[1] == "r":
        menupos = menupos.replace("left:0", "right:0")
    menumob = "bottom:72px" if canto[0] == "b" else "top:72px"
    js = (_I18N_JS.replace("__PADRAO__", padrao)
                  .replace("__CANTO__", pos)
                  .replace("__MENUPOS__", menupos)
                  .replace("__MENUMOB__", menumob)
                  .replace("__AUTO__", "1" if auto else "0"))
    return '<script data-clone="i18n">' + js + "</script>"


def link_snippet(dest):
    """Manda TODA navegação para o destino, sem quebrar a UI.

    - sobrescreve funções de troca de página (nextPage, goToCheckout...);
    - intercepta cliques em <a>/<button>/onclick que levam a outra página;
    - intercepta o submit de formulários.
    O que permanece na página — âncoras internas (#) e elementos de FAQ,
    slider, menu — não é redirecionado.
    """
    d = dest.replace("\\", "\\\\").replace('"', '\\"')
    return (
        '<script data-clone="link">\n'
        '(function(){var DEST="' + d + '";\n'
        'var UI=/faq|accordion|collaps|toggle|question|answer|swiper|splide|'
        'slider|carousel|\\btabs?\\b|dropdown|hamburger|menu|modal|popup|'
        'lightbox|tooltip|counter|countdown|timer|lang|idioma|locale|switcher/i;\n'
        'function cls(el){if(!el||el.className==null)return "";'
        'var c=el.className;return (c.baseVal!==undefined?c.baseVal:c)+"";}\n'
        'function ui(el){while(el&&el!==document.documentElement){'
        'if(UI.test(cls(el)))return true;if(el.getAttribute){'
        'if(el.hasAttribute("data-clone-lang")||el.hasAttribute("data-clone-ui"))return true;'
        'if(UI.test(el.getAttribute("id")||""))return true;'
        'var r=el.getAttribute("role")||"";if(/tab|menuitem|switch/.test(r))return true;}'
        'el=el.parentElement;}return false;}\n'
        'function interno(h){return !h||h.charAt(0)==="#"||h.indexOf("javascript:")===0;}\n'
        '["nextPage","goToCheckout","goToOrder","redirectToCheckout","toCheckout",'
        '"gotoCheckout"].forEach(function(f){try{window[f]=function(){location.href=DEST;};}catch(_){}});\n'
        'function fix(){var as=document.querySelectorAll("a[href]");'
        'for(var i=0;i<as.length;i++){var a=as[i];var h=a.getAttribute("href");'
        'if(interno(h)||ui(a))continue;a.setAttribute("href",DEST);'
        'a.removeAttribute("target");a.removeAttribute("onclick");}}\n'
        'fix();document.addEventListener("DOMContentLoaded",fix);\n'
        'function nav(el){while(el&&el!==document.documentElement){'
        'var t=el.tagName?el.tagName.toLowerCase():"";'
        'if(t==="a"){return interno(el.getAttribute("href"))?null:el;}'
        'if(t==="button"){if((el.getAttribute("type")||"").toLowerCase()!=="reset")return el;}'
        'if(t==="input"){var y=(el.type||"").toLowerCase();'
        'if(y==="submit"||y==="button"||y==="image")return el;}'
        'if(el.getAttribute&&el.hasAttribute("onclick"))return el;'
        'el=el.parentElement;}return null;}\n'
        'document.addEventListener("click",function(e){'
        'if(ui(e.target))return;if(nav(e.target)){e.preventDefault();e.stopPropagation();'
        'if(e.stopImmediatePropagation)e.stopImmediatePropagation();location.href=DEST;}},true);\n'
        'document.addEventListener("submit",function(e){'
        'if(ui(e.target))return;e.preventDefault();location.href=DEST;},true);\n'
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
                idioma="", idiomas="", idioma_pos="bl", sem_idiomas=False, idioma_auto=False,
                idioma_origem="", sem_traduzir=False):
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

    def montar(html):
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
                    # o src pode ter virado "assets/xxx.js" e escondido o domínio:
                    # a decisão olha a URL de ORIGEM.
                    origem = local2url.get(alvo.split("?")[0], "") or alvo
                    u = (origem + " " + alvo).lower()
                    for t in TRACKER_DOMINIOS:
                        if t in u: porque = t; break
                    if not porque and not any(k in u for k in UI_KEEP):
                        for t in TRACKER_SRC:
                            if t in u: porque = t; break
                else:
                    for t in TRACKER_INLINE:
                        if t in corpo: porque = t; break
                if not porque:
                    return m.group(0)
                mortos.append(porque)
                return ('<script type="text/plain" data-clone-disabled="%s"%s>%s</script>'
                        % (porque, attrs, corpo))

            html = re.sub(r"<script\b([^>]*)>(.*?)</script>", mata, html, flags=re.S)
            html, n_ns = re.subn(r"<noscript><iframe[^>]*(?:googletagmanager|facebook)[^>]*>.*?</noscript>",
                                 "<!-- tracker noscript removido -->", html, flags=re.S)

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
                    html = re.sub(r"(<head\b[^>]*>)", lambda m: m.group(1) + STUBS, html, count=1)
                diga("LIMPEZA: %s" % ", ".join("%s=%d" % (k, v) for k, v in c.items() if v))

        if link:
            # Padrão: TODA navegação (troca de página, link externo, botão de
            # checkout, submit de formulário) vai para o link fornecido. O que
            # permanece na página — âncoras internas (#) e interações de UI
            # (FAQ, slider, menu) — não é tocado.
            alvo = link.replace("\\", "\\\\").replace('"', "&quot;")

            # (1) Reescrita estática do href dos <a> que trocam de página / são
            #     externos (mantém âncoras internas), para o hover mostrar o link.
            def troca_a(m):
                tag = m.group(0)
                if "data-clone-lang" in tag:
                    return tag           # seletor de idioma: navegação interna
                h = re.search(r'href="([^"]*)"', tag)
                if h and (h.group(1).startswith("#") or h.group(1).startswith("javascript:")):
                    return tag                       # âncora interna / js: preserva
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
            html = html.replace("</body>", link_snippet(link) + "\n</body>", 1) \
                if "</body>" in html else html + link_snippet(link)

        if redirect:
            # depois da limpeza: entra no fim do <body> para rodar por último
            snip = redirect_snippet(redirect)
            if "</body>" in html:
                html = html.replace("</body>", snip + "\n</body>", 1)
            else:
                html += snip
            diga("REDIRECT: todo clique -> %s" % redirect)
        return html

    html = relocalizar(html)

    # ── 3b. idiomas ───────────────────────────────────────────────
    # Todo clone sai com seletor de idioma próprio: um botão flutuante
    # isolado em Shadow DOM, que não depende do frontend da página.
    #
    #   --idiomas "pt-br,en,de"  -> o PRIMEIRO é o padrão, e os três ficam
    #                               disponíveis para trocar no site.
    #
    # A página clonada tem o idioma que tem (o <html lang>). Todo idioma
    # pedido que não seja esse precisa de dicionário, e ele vem, nesta ordem:
    #   1. da versão que o servidor de origem devolveu (capturar.js as busca);
    #   2. de i18n/<código>.json já na pasta (cache de rodadas anteriores);
    #   3. traduzido na hora pelo CLI do Claude, e salvo como cache.
    vindos = {k.lower(): v for k, v in (d.get("idiomas") or {}).items()}
    base_lang = (idioma_origem or
                 (re.search(r'<html[^>]*\blang="([^"]+)"', html) or [None, ""])[1]
                 or next((k for k, v in vindos.items() if v.get("atual")), "")
                 or "pt-br").lower()

    pedidos = [c.strip().lower() for c in idiomas.split(",") if c.strip()]
    # o primeiro da lista manda; --idioma continua valendo como atalho
    padrao = (idioma or (pedidos[0] if pedidos else "") or base_lang).lower()
    oferecidos = pedidos or sorted(vindos) or [base_lang]
    if padrao not in oferecidos:
        oferecidos.insert(0, padrao)
    oferecidos = [padrao] + [c for c in oferecidos if c != padrao]

    pasta_i18n = os.path.join(out, "i18n")
    dicio, fonte = {}, {}
    base_para_dic = html            # antes de qualquer injeção nossa

    if not sem_idiomas:
        # (1) versões traduzidas que vieram na captura
        for c, v in sorted(vindos.items()):
            if c == base_lang or c not in oferecidos or not v.get("html"):
                continue
            dic, cont = dicionario_da_variante(base_para_dic, v["html"])
            if dic:
                dicio[c], fonte[c] = dic, "origem"
            else:
                print("   idioma %s: %d vs %d segmentos — template diferente, "
                      "vai por tradução" % (c, cont[0], cont[1]))

        # (2) cache em disco
        if os.path.isdir(pasta_i18n):
            for fn in sorted(os.listdir(pasta_i18n)):
                if not fn.endswith(".json") or fn.startswith("_"):
                    continue
                c = fn[:-5].lower()
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

    if sem_idiomas:
        html = montar(html)
    else:
        html, n_marc = marcar_idiomas(html, set(oferecidos) | set(vindos))
        html = montar(html)
        os.makedirs(pasta_i18n, exist_ok=True)

        # (3) o que ainda falta, traduzido agora
        base = segmentos(html)      # já limpo: sem sobra de tracker
        termos = sorted(set(base.textos) | set(base.atributos) |
                        ({base.titulo} if base.titulo else set()))
        io.open(os.path.join(pasta_i18n, "_base.json"), "w", encoding="utf-8").write(
            json.dumps({t: "" for t in termos}, ensure_ascii=False, indent=1))

        pendentes = [c for c in oferecidos
                     if c != base_lang and len(dicio.get(c, {})) < len(termos) * 0.6]
        if pendentes and not sem_traduzir:
            print("traduzindo %d termos de %s para: %s"
                  % (len(termos), base_lang, ", ".join(pendentes)))
            for c in pendentes:
                falta = [t for t in termos if t not in dicio.get(c, {})]
                novo_dic = traduzir_termos(falta, base_lang, c)
                if novo_dic:
                    dicio.setdefault(c, {}).update(novo_dic)
                    fonte[c] = "traduzido" if fonte.get(c) is None else fonte[c] + "+traduzido"
                    io.open(os.path.join(pasta_i18n, c + ".json"), "w",
                            encoding="utf-8").write(json.dumps(
                                dicio[c], ensure_ascii=False, indent=1, sort_keys=True))
        elif pendentes:
            print("   sem dicionário (--sem-traduzir): %s" % ", ".join(pendentes))

        codigos = [c for c in oferecidos if c == base_lang or dicio.get(c)]
        escrever_i18n(pasta_i18n, base_lang, dicio, codigos)

        # dicionário antes do widget, widget antes do --link: quem registra
        # o clique primeiro ganha a troca de idioma.
        snip = ('<script src="i18n/dicionarios.js"></script>\n'
                + i18n_snippet(padrao, idioma_pos, idioma_auto))
        marca_link = '<script data-clone="link">'
        if marca_link in html:
            html = html.replace(marca_link, snip + "\n" + marca_link, 1)
        elif "</body>" in html:
            html = html.replace("</body>", snip + "\n</body>", 1)
        else:
            html += snip

        print("idiomas: página em %s | padrão %s | no seletor: %s%s"
              % (base_lang, padrao, ", ".join(codigos),
                 " | %d opções nativas religadas" % n_marc if n_marc else ""))
        for c in codigos:
            if c == base_lang:
                print("   %-9s %4d termos (texto original da página)" % (c, len(termos)))
            else:
                print("   %-9s %4d/%d termos (%s)"
                      % (c, len(dicio[c]), len(termos), fonte.get(c, "?")))
        fora = [c for c in oferecidos if c not in codigos]
        if fora:
            print("   FORA do seletor (sem dicionário): %s" % ", ".join(fora))

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
    ap.add_argument("--idioma", default="", metavar="COD",
                    help="atalho: força o idioma padrão. Normalmente basta pôr ele "
                         "em primeiro na lista de --idiomas")
    ap.add_argument("--idiomas", default="", metavar="LISTA",
                    help="idiomas disponíveis no seletor, separados por vírgula. "
                         "O PRIMEIRO é o padrão do clone. Ex.: pt-br,en,de")
    ap.add_argument("--idioma-origem", default="", metavar="COD",
                    help="idioma em que a página capturada está "
                         "(padrão: o <html lang> dela)")
    ap.add_argument("--sem-traduzir", action="store_true",
                    help="não chama o Claude para traduzir o que faltar; usa só "
                         "o que veio da captura e os i18n/<cod>.json existentes")
    ap.add_argument("--idioma-pos", default="bl", choices=sorted(CANTOS),
                    help="canto do botão flutuante: bl/br/tl/tr (padrão bl)")
    ap.add_argument("--idioma-auto", action="store_true",
                    help="na 1ª visita, abre no idioma do navegador se houver "
                         "dicionário (padrão: abre sempre em --idioma)")
    ap.add_argument("--sem-idiomas", action="store_true",
                    help="não injeta o seletor de idioma")
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
                so_frontend=a.so_frontend, link=a.link,
                idioma=a.idioma, idiomas=a.idiomas, idioma_pos=a.idioma_pos,
                sem_idiomas=a.sem_idiomas, idioma_auto=a.idioma_auto,
                idioma_origem=a.idioma_origem, sem_traduzir=a.sem_traduzir)


if __name__ == "__main__":
    main()
