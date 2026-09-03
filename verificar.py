#!/usr/bin/env python3
"""
CLONADOR DE PÁGINAS — CONFERÊNCIA

Diz, sem abrir o navegador, se um clone está inteiro.

Uso:  ./verificar.py <nome-do-clone>          (uma pasta em clones/)
      ./verificar.py caminho/da/pasta
      ./verificar.py ~/Downloads/clone.zip    (confere o zip baixado)
      ./verificar.py                          (confere TODOS os clones)

Sai com código 1 se achou buraco — dá para usar em script.

O que a auditoria do clonar.py não via: ela contava só os assets citados
no HTML. Imagem de fundo mora dentro do CSS, e era exatamente ali que
faltava arquivo sem ninguém perceber.
"""
import io, json, os, re, sys, tempfile, zipfile, shutil
from urllib.parse import unquote, urlsplit

RAIZ = os.path.dirname(os.path.abspath(__file__))
CLONES = os.path.join(RAIZ, "clones")

# Extensões que são arquivo de verdade — o resto (rota, âncora, sufixo de
# template) não é asset e não entra na conta.
ASSET = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif", ".bmp",
         ".ico", ".mp4", ".webm", ".m4v", ".ogg", ".mp3", ".wav",
         ".woff", ".woff2", ".ttf", ".otf", ".eot", ".css", ".js", ".json",
         ".html", ".htm", ".pdf")

# Sujeira de JS/template que parece caminho e não é: `${x}`, "+c+", "{{y}}".
LIXO = re.compile(r"[\$\{\}<>+`\\]|\s")

EXTERNO = re.compile(r"^(?:https?:|//|data:|blob:|about:|mailto:|tel:|javascript:|#|chrome-extension:)", re.I)


def local(u):
    """Devolve o caminho local que essa referência aponta, ou None."""
    u = (u or "").strip()
    if not u or EXTERNO.match(u) or LIXO.search(u):
        return None
    u = unquote(u.split("#")[0].split("?")[0])
    if not u or u.endswith("/"):
        return None
    if os.path.splitext(u)[1].lower() not in ASSET:
        return None
    return u


def refs_html(texto):
    """(url, rótulo) de tudo que o navegador busca sozinho num HTML.

    Script de tracker neutralizado sai fora: o clonador marcou de propósito
    e o navegador não vai buscar — apontar isso como falta seria ruído.
    """
    texto = re.sub(r"<script\b[^>]*data-clone-disabled.*?</script>", "",
                   texto, flags=re.S | re.I)
    texto = re.sub(r"<[^>]*\bdata-clone-disabled\b[^>]*>", "", texto)
    for m in re.finditer(r'\b(src|poster|data-src|data-lazy-src|data-original)\s*=\s*"([^"]*)"', texto, re.I):
        yield m.group(2), m.group(1)
    for m in re.finditer(r'<link\b[^>]*\bhref\s*=\s*"([^"]*)"', texto, re.I):
        yield m.group(1), "link"
    for m in re.finditer(r'\bsrcset\s*=\s*"([^"]*)"', texto, re.I):
        for parte in m.group(1).split(","):
            p = parte.strip().split()
            if p:
                yield p[0], "srcset"
    for m in re.finditer(r'\bstyle\s*=\s*"([^"]*)"', texto, re.I):
        for u in re.findall(r"url\(\s*['\"]?([^'\")]+)", m.group(1)):
            yield u, "style"
    # og:image e afins não aparecem na tela, mas quebram o preview do link
    for m in re.finditer(r'<meta\b[^>]*(?:property|name)\s*=\s*"(og:image[^"]*|twitter:image[^"]*)"[^>]*>', texto, re.I):
        c = re.search(r'content\s*=\s*"([^"]*)"', m.group(0), re.I)
        if c:
            yield c.group(1), "meta:" + m.group(1)


def refs_css(texto):
    for m in re.finditer(r"url\(\s*['\"]?([^'\")]+)", texto):
        yield m.group(1), "url()"
    for m in re.finditer(r"@import\s+['\"]([^'\"]+)['\"]", texto):
        yield m.group(1), "@import"


def externos(texto):
    """Domínios que a página chama SOZINHA ao abrir (não conta <a>)."""
    fora = set()
    vivo = re.sub(r"<script\b[^>]*data-clone-disabled.*?</script>", "", texto, flags=re.S | re.I)
    for m in re.finditer(r'(?:\bsrc|<link[^>]+href)\s*=\s*"(https?://[^"]+)"', vivo, re.I):
        fora.add(urlsplit(m.group(1)).netloc)
    for m in re.finditer(r"url\(\s*['\"]?(https?://[^'\")]+)", vivo):
        fora.add(urlsplit(m.group(1)).netloc)
    fora.discard("www.w3.org")
    fora.discard("")
    return fora


def conferir(pasta, quieto=False, origem_404=None, ficha=None, link=None):
    """Confere um clone já montado. Devolve (problemas, resumo).

    `origem_404` são os nomes de arquivo que JÁ davam 404/403 no site de
    origem (o clonador tira isso do log da captura). Eles aparecem no
    relatório, mas não contam como problema: o clone estar sem uma imagem
    que a própria origem não entrega é fidelidade, não buraco. Sem essa
    separação a conferência vira alarme falso e a gente para de olhar.
    """
    def diz(*x):
        if not quieto:
            print(*x)

    nome = os.path.basename(pasta.rstrip("/"))
    problemas = []
    origem_404 = set(origem_404 or ())

    if ficha is None:
        ficha = {}
        fp = os.path.join(pasta, ".clone.json")
        if not os.path.exists(fp):
            # zip baixado não leva a ficha; se o clone ainda existe aqui,
            # empresta a dele para poder conferir link e 404s de origem
            irmao = os.path.join(CLONES, nome, ".clone.json")
            if os.path.exists(irmao):
                fp = irmao
                diz("ficha : emprestada de clones/%s" % nome)
        if os.path.exists(fp):
            try:
                ficha = json.load(io.open(fp, encoding="utf-8"))
            except Exception:
                ficha = {}
    if not origem_404:
        origem_404 = set(ficha.get("404_origem") or ())

    diz("=" * 62)
    diz("clone : %s" % nome)
    if ficha.get("origem"):
        diz("origem: %s" % ficha["origem"])
        diz("feito : %s" % ficha.get("quando", "?"))

    # ── 1. estrutura mínima ───────────────────────────────────────
    index = os.path.join(pasta, "index.html")
    if not os.path.exists(index):
        problemas.append("index.html não existe")
        diz("\n[FALHA] index.html não existe")
        return problemas, {}
    assets = os.path.join(pasta, "assets")
    n_assets = len(os.listdir(assets)) if os.path.isdir(assets) else 0
    if not n_assets:
        problemas.append("assets/ vazio ou ausente")

    # ── 2. toda referência local, de todo HTML e todo CSS ─────────
    # A resolução é relativa AO ARQUIVO que cita — é isso que a auditoria
    # antiga não fazia, e por isso um url() dentro de assets/x.css passava.
    arquivos = []
    for d, _, fs in os.walk(pasta):
        for f in fs:
            e = f.lower()
            if e.endswith((".html", ".htm", ".css")):
                arquivos.append(os.path.join(d, f))

    faltando, vistas = {}, 0
    for p in sorted(arquivos):
        try:
            t = io.open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        base = os.path.dirname(p)
        gera = refs_css(t) if p.lower().endswith(".css") else refs_html(t)
        for bruto, rotulo in gera:
            c = local(bruto)
            if c is None:
                continue
            vistas += 1
            # "/x/y.png" é absoluto: resolve contra a RAIZ DO CLONE, que é
            # o que um servidor faz. Contra a raiz do disco daria um monte
            # de "../../.." e um falso positivo em cada linha.
            if c.startswith("/"):
                alvo = os.path.normpath(os.path.join(pasta, c.lstrip("/")))
            else:
                alvo = os.path.normpath(os.path.join(base, c))
            if os.path.exists(alvo):
                continue
            # último recurso: o clonador achata tudo em assets/, então um
            # ../x.png que não existe pode estar lá pelo nome
            if os.path.exists(os.path.join(assets, os.path.basename(c))):
                continue
            faltando.setdefault(
                os.path.relpath(alvo, pasta),
                (os.path.relpath(p, pasta), bruto, rotulo))

    # ── 3. chamadas externas automáticas ──────────────────────────
    fora = set()
    for p in arquivos:
        if p.lower().endswith((".html", ".htm")):
            fora |= externos(io.open(p, encoding="utf-8", errors="replace").read())

    # ── 4. <a> apontando para o link de afiliado ──────────────────
    html = io.open(index, encoding="utf-8", errors="replace").read()
    # o <a> do seletor de idioma fica de fora: ele não sai da página, e
    # contá-lo como "não vai para a oferta" seria alarme falso
    hrefs = []
    for m in re.finditer(r"<a\b([^>]*)>", html, re.I):
        atrs = m.group(1)
        if "data-clone-lang" in atrs:
            continue
        h = re.search(r'\bhref\s*=\s*"([^"]*)"', atrs, re.I)
        if h:
            hrefs.append(h.group(1))
    destino = link if link is not None else (ficha.get("link_afiliado") or "")
    para_oferta = sum(1 for h in hrefs if destino and h.startswith(destino))
    ancoras = sum(1 for h in hrefs if h.startswith("#"))
    # só o atributo de verdade: a string também aparece dentro do JS de
    # idioma injetado, e contá-la lá inflava o número
    sem_js = re.sub(r"<script\b.*?</script>", "", html, flags=re.S | re.I)
    idioma = len(re.findall(r'\bdata-clone-lang\s*=', sem_js))

    # ── relatório ─────────────────────────────────────────────────
    nossos = {k: v for k, v in faltando.items()
              if os.path.basename(k) not in origem_404}
    da_origem = {k: v for k, v in faltando.items() if k not in nossos}

    diz("\n-- REFERÊNCIAS LOCAIS")
    diz("   conferidas: %d em %d arquivo(s) | assets no disco: %d"
        % (vistas, len(arquivos), n_assets))
    if nossos:
        problemas.append("%d referência(s) local(is) quebrada(s)" % len(nossos))
        diz("   [FALHA] %d não existem no disco:" % len(nossos))
        for alvo, (onde, bruto, rotulo) in sorted(nossos.items()):
            diz("      %-46s  <- %s (%s)" % (alvo[:46], onde, rotulo))
    else:
        diz("   [OK] todas resolvem para um arquivo existente")
    if da_origem:
        diz("   (%d já davam 404/403 no site de origem — o original também "
            "não mostra:)" % len(da_origem))
        for alvo, (onde, bruto, rotulo) in sorted(da_origem.items()):
            diz("      %-46s  <- %s" % (alvo[:46], onde))

    diz("\n-- CHAMADAS EXTERNAS AUTOMÁTICAS")
    if fora:
        problemas.append("%d domínio(s) chamado(s) ao abrir" % len(fora))
        diz("   [FALHA] a página busca sozinha em:")
        for dom in sorted(fora):
            diz("      -", dom)
    else:
        diz("   [OK] nenhuma — o clone não telefona para ninguém")

    diz("\n-- LINKS E IDIOMA")
    if destino:
        outros = len(hrefs) - para_oferta - ancoras
        diz("   <a>: %d no total | %d para a oferta | %d âncora interna | %d outros"
            % (len(hrefs), para_oferta, ancoras, outros))
        if outros:
            problemas.append("%d <a> não vão para a oferta" % outros)
            diz("   [FALHA] estes não vão para a oferta:")
            for h in [h for h in hrefs
                      if not h.startswith("#") and not h.startswith(destino)][:8]:
                diz("      %s" % h[:80])
        else:
            diz("   [OK] toda saída vai para a oferta")
    else:
        diz("   <a>: %d (clone sem --link; nada a conferir)" % len(hrefs))
    diz("   opções de idioma marcadas (data-clone-lang): %d" % idioma)

    diz("")
    if problemas:
        diz(">>> %d PROBLEMA(S): %s" % (len(problemas), "; ".join(problemas)))
    else:
        diz(">>> CLONE ÍNTEGRO — nada faltando, nada externo, links no lugar")

    return problemas, {"refs": vistas, "faltando": len(nossos),
                       "faltando_lista": sorted(nossos),
                       "faltando_origem": sorted(da_origem),
                       "externos": sorted(fora), "assets": n_assets}


def main():
    alvos, tmp = [], None
    if len(sys.argv) < 2:
        if not os.path.isdir(CLONES):
            sys.exit("não há clones/ para conferir")
        alvos = [os.path.join(CLONES, d) for d in sorted(os.listdir(CLONES))
                 if os.path.isdir(os.path.join(CLONES, d))]
        if not alvos:
            sys.exit("clones/ está vazio")
    else:
        alvo = os.path.expanduser(sys.argv[1])
        if alvo.lower().endswith(".zip"):
            if not os.path.exists(alvo):
                sys.exit("ERRO: %s não existe" % alvo)
            tmp = tempfile.mkdtemp(prefix="verificar-")
            with zipfile.ZipFile(alvo) as z:
                z.extractall(tmp)
            dentro = [os.path.join(tmp, d) for d in os.listdir(tmp)]
            raiz = dentro[0] if len(dentro) == 1 and os.path.isdir(dentro[0]) else tmp
            print("zip   : %s" % alvo)
            alvos = [raiz]
        elif os.path.isdir(alvo):
            alvos = [alvo]
        elif os.path.isdir(os.path.join(CLONES, alvo)):
            alvos = [os.path.join(CLONES, alvo)]
        else:
            sys.exit("ERRO: não achei clone nem pasta nem zip em %r" % alvo)

    try:
        ruins = 0
        for p in alvos:
            probs, _ = conferir(p)
            if probs:
                ruins += 1
            print()
        if len(alvos) > 1:
            print("=" * 62)
            print("%d clone(s) conferido(s) — %d com problema" % (len(alvos), ruins))
        sys.exit(1 if ruins else 0)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
