#!/usr/bin/env python3
"""Abre o clone E o original num Chrome de verdade e compara os dois.

    ./conferir.py <nome-do-clone>
    ./conferir.py <nome-do-clone> --origem "https://site/pagina"

Por que existe, se já existe o `verificar.py`: eles respondem perguntas
diferentes, e a diferença já custou imagem.

  `verificar.py` pergunta "todo arquivo citado existe no disco?". É rápido,
  não abre navegador, e é o que roda no fim de toda clonagem.

  Aqui a pergunta é outra: "a página PEDE as mesmas coisas que a original
  pedia?". Um asset pode estar no disco sem ninguém citá-lo, e uma imagem
  que só o JavaScript conhecia pode ter sumido junto com o script que a
  citava — nos dois casos o `verificar.py` diz que está tudo certo, e falta
  imagem na tela.

O que se compara, com os dois rolados até o fim:

  * a mídia que cada lado pediu (o clone renomeia por colisão, então o
    prefixo de hash sai antes de comparar);
  * imagem quebrada — a que o navegador pediu e voltou vazia. Imagem
    `lazy` em seção escondida nunca é pedida, nos dois lados, e isso NÃO
    é buraco: é o mesmo comportamento do original;
  * erro de JavaScript que só o clone tem — é o sintoma de um global que
    saiu junto com o rastreamento e derrubou o resto do arquivo;
  * chamada externa, que no clone tem de ser zero.

A diferença esperada no total de recursos é exatamente o rastreamento:
o original pede mais, e o que ele pede a mais são os trackers.
"""
import argparse, io, json, os, re, socket, subprocess, sys, time

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)
from cdp import Chrome                                          # noqa: E402
import capturar as cap                                          # noqa: E402
from clonar import eh_tracker                                   # noqa: E402

CLONES = os.path.join(RAIZ, "clones")

# Anota erro de JS e recurso, antes de a página começar. window.onerror não
# pega tudo (promessa rejeitada escapa), daí os dois ouvintes.
PREAMBULO = """
(function () {
  try { performance.setResourceTimingBufferSize(20000); } catch (e) {}
  window.__ERROS = [];
  addEventListener('error', function (e) {
    // Dois eventos diferentes chegam por aqui e o nome é o mesmo: erro de
    // script (tem message) e recurso que não carregou (tem target). Sem
    // separar, o relatório dizia só "error" e não dava para achar nada.
    var alvo = e && e.target;
    if (alvo && alvo !== window && alvo.tagName) {
      window.__ERROS.push('não carregou <' + alvo.tagName.toLowerCase() + '> ' +
        String(alvo.currentSrc || alvo.src || alvo.href || '').slice(-90));
      return;
    }
    window.__ERROS.push(String((e && e.message) || 'erro') +
      (e && e.filename ? '  em ' + String(e.filename).split('/').pop() +
       ':' + (e.lineno || 0) : ''));
  }, true);
  addEventListener('unhandledrejection', function (e) {
    window.__ERROS.push('promessa: ' + String((e && e.reason) || ''));
  });
})();
"""

# Rola tudo e espera o lazy-load assentar. É a mesma rolagem da captura:
# sem ela, metade da página nunca é pedida e a comparação não vale nada.
ROLAR = """(async () => {
  const h = () => Math.max(document.body.scrollHeight,
                           document.documentElement.scrollHeight);
  const p = Math.max(300, innerHeight * 0.8);
  for (let y = 0; y < h(); y += p) {
    scrollTo(0, y);
    await new Promise(r => setTimeout(r, 200));
  }
  scrollTo(0, h());
  await new Promise(r => setTimeout(r, 1800));
  scrollTo(0, 0);
  await new Promise(r => setTimeout(r, 800));
  return 1;
})()"""

MEDIR = r"""(function () {
  var quebradas = [], adiadas = 0;
  document.querySelectorAll('img').forEach(function (i) {
    var u = i.currentSrc || i.src;
    if (!u) return;
    // pedida e voltou vazia = quebrada. Ainda não pedida = lazy escondida,
    // que o original também não pede — não conta.
    if (i.complete && i.naturalWidth === 0) quebradas.push(u);
    else if (!i.complete) adiadas++;
  });
  var videos = [];
  document.querySelectorAll('video').forEach(function (v) {
    if ((v.src || v.currentSrc) && v.readyState === 0)
      videos.push(v.src || v.currentSrc);
  });
  var r = performance.getEntriesByType('resource');
  var fora = {};
  r.forEach(function (e) {
    try {
      var o = new URL(e.name).origin;
      if (o !== location.origin) fora[o] = (fora[o] || 0) + 1;
    } catch (x) {}
  });
  return JSON.stringify({
    nomes: r.map(function (e) { return e.name; }),
    quebradas: quebradas, adiadas: adiadas, videos: videos,
    fora: fora, erros: (window.__ERROS || []).slice(0, 40),
    altura: Math.max(document.body.scrollHeight,
                     document.documentElement.scrollHeight),
    elementos: document.querySelectorAll('*').length,
    titulo: document.title
  });
})()"""

MIDIA = re.compile(
    r"\.(png|jpe?g|gif|webp|avif|svg|bmp|ico|mp4|webm|ogv|mov|m4v|"
    r"mp3|m4a|wav|woff2?|ttf|otf|eot|css|js)($|\?)", re.I)
# o clonador prefixa md5[:6]_ quando dois arquivos disputam o mesmo nome
HASH = re.compile(r"^[0-9a-f]{6}_")
# ...e troca por "_" o que não for [A-Za-z0-9._-]. Sem desfazer isso aqui,
# "4,5-stars.svg" no original e "4_5-stars.svg" no clone parecem dois
# arquivos diferentes, e a comparação acusa uma falta que não existe.
FEIO = re.compile(r"[^A-Za-z0-9._-]")


def nome_de(u):
    n = u.split("?")[0].split("#")[0].rstrip("/").split("/")[-1]
    from urllib.parse import unquote
    return FEIO.sub("_", HASH.sub("", unquote(n))).lower()


def midias(nomes):
    return {nome_de(u) for u in nomes if MIDIA.search(u.split("#")[0])}


def medir(c, sess, url, rotulo):
    print("   abrindo %s: %s" % (rotulo, url[:80]))
    c.cmd("Page.navigate", {"url": url}, sessao=sess, espera=120)
    c.eventos_ate("Page.loadEventFired", espera=90)
    time.sleep(3)
    c.cmd("Runtime.evaluate", {"expression": ROLAR, "awaitPromise": True},
          sessao=sess, espera=240)
    time.sleep(2)
    r = c.cmd("Runtime.evaluate", {"expression": MEDIR, "returnByValue": True},
              sessao=sess, espera=60).get("result", {}).get("value", "{}")
    return json.loads(r)


def porta_livre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def servidor_do_clone(nome):
    """Devolve (url, processo). Usa o painel se ele já estiver de pé.

    Servir importa: em file:// o navegador trata cada arquivo como origem
    opaca, e metade do JavaScript da página nem roda — a comparação sairia
    errada por um motivo que não é do clone.
    """
    try:
        import urllib.request
        urllib.request.urlopen("http://127.0.0.1:7000/", timeout=2).read(64)
        return "http://127.0.0.1:7000/c/%s/" % nome, None
    except Exception:
        pass
    p = porta_livre()
    proc = subprocess.Popen(
        [sys.executable, os.path.join(RAIZ, "servir.py"), nome, str(p)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        try:
            import urllib.request
            urllib.request.urlopen("http://127.0.0.1:%d/" % p, timeout=1).read(64)
            return "http://127.0.0.1:%d/" % p, proc
        except Exception:
            time.sleep(0.25)
    proc.terminate()
    sys.exit("ERRO: não consegui servir o clone %r." % nome)


def conferir(nome, origem="", porta=9223, visivel=False):
    pasta = nome if os.path.isdir(nome) else os.path.join(CLONES, nome)
    if not os.path.isdir(pasta):
        sys.exit("ERRO: clone %r não existe em %s" % (nome, CLONES))
    ficha = {}
    fp = os.path.join(pasta, ".clone.json")
    if os.path.exists(fp):
        try:
            ficha = json.load(io.open(fp, encoding="utf-8"))
        except Exception:
            pass
    origem = origem or ficha.get("origem") or ""
    if not origem:
        sys.exit("ERRO: não sei qual é a página original. Passe --origem.")

    url_clone, srv = servidor_do_clone(os.path.basename(pasta.rstrip("/")))
    # Se já há um Chrome com a porta de depuração aberta, é nele que a
    # comparação roda — e isso importa: VPN de extensão só vale na sessão
    # em que alguém clicou em "conectar", então subir um Chrome novo abriria
    # o original pelo IP de casa e levaria o bloqueio que a página capturada
    # não levou. Sem ninguém de pé, sobe tela virtual e navegador próprios.
    ja = cap.vivo(porta)
    xproc, display = (None, None) if ja else cap.sobe_xvfb()
    proc = cap.sobe_chrome(porta, True, display, "")
    alvo = None
    try:
        c = Chrome(porta)
        alvo = c.cmd("Target.createTarget", {"url": "about:blank"})["targetId"]
        aberto = c
        sess = c.cmd("Target.attachToTarget",
                     {"targetId": alvo, "flatten": True})["sessionId"]
        c.cmd("Page.enable", sessao=sess)
        c.cmd("Runtime.enable", sessao=sess)
        c.cmd("Page.addScriptToEvaluateOnNewDocument",
              {"source": PREAMBULO}, sessao=sess)
        o = medir(c, sess, origem, "original")
        k = medir(c, sess, url_clone, "clone")
        try:
            c.cmd("Target.closeTarget", {"targetId": alvo})   # não deixa aba órfã
        except Exception:
            pass
        alvo = None
        c.fechar()
        no_disco = set()
        pa = os.path.join(pasta, "assets")
        if os.path.isdir(pa):
            no_disco = {nome_de(f) for f in os.listdir(pa)}
    finally:
        if proc:
            proc.terminate()
        if xproc:
            xproc.terminate()
        if srv:
            srv.terminate()

    return relatar(nome, origem, o, k, no_disco)


def relatar(nome, origem, o, k, no_disco=()):
    problemas = []
    mo, mk = midias(o["nomes"]), midias(k["nomes"])
    no_disco = set(no_disco)

    # De onde o original pediu cada coisa: sem a URL não dá para dizer se
    # aquilo era rastreamento, e o nome do arquivo sozinho não entrega.
    url_de = {}
    for u in o["nomes"]:
        url_de.setdefault(nome_de(u), u)

    # A diferença tem três leituras, e só uma é buraco:
    #   tracker      — o clone não pedir É o trabalho feito;
    #   está no disco — veio junto, só ninguém pediu nesta visita (script de
    #                   UI que já rodou na captura, imagem de seção que só
    #                   abre no clique). O arquivo está lá quando precisar;
    #   ausente      — não pediu e não tem. Esse é o buraco.
    trackers, guardados, faltando = [], [], []
    for n in sorted(mo - mk):
        if eh_tracker(url_de.get(n, n)):
            trackers.append(n)
        elif n in no_disco:
            guardados.append(n)
        else:
            faltando.append(n)

    print("\n" + "=" * 62)
    print("clone : %s" % nome)
    print("origem: %s" % origem)

    print("\n-- O QUE CADA LADO PEDIU")
    print("   recursos : original %d | clone %d" % (len(o["nomes"]), len(k["nomes"])))
    print("   mídia    : original %d | clone %d" % (len(mo), len(mk)))
    if faltando:
        problemas.append("%d mídia(s) que o original pede e o clone não tem"
                         % len(faltando))
        print("   [FALHA] o original pede, o clone não pede e não tem:")
        for n in faltando[:40]:
            print("      %s" % n)
        if len(faltando) > 40:
            print("      … e mais %d" % (len(faltando) - 40))
    else:
        print("   [OK] nada que o original pede ficou de fora do clone")
    if trackers:
        print("   (%d era(m) rastreamento e saiu(íram) de propósito: %s)"
              % (len(trackers), ", ".join(trackers[:6])
                 + (" …" if len(trackers) > 6 else "")))
    if guardados:
        print("   (%d não foi(ram) pedido(s) nesta visita, mas está(ão) no "
              "clone: %s)" % (len(guardados), ", ".join(guardados[:6])
                              + (" …" if len(guardados) > 6 else "")))

    print("\n-- IMAGEM E VÍDEO NA TELA")
    print("   imagens quebradas : original %d | clone %d"
          % (len(o["quebradas"]), len(k["quebradas"])))
    novas = [u for u in k["quebradas"]
             if nome_de(u) not in {nome_de(x) for x in o["quebradas"]}]
    if novas:
        problemas.append("%d imagem(ns) quebrada(s) só no clone" % len(novas))
        print("   [FALHA] quebradas só no clone:")
        for u in novas[:20]:
            print("      %s" % u[:100])
    else:
        print("   [OK] nenhuma imagem quebra no clone que não quebre no original")
    print("   nem pedidas (lazy escondida): original %d | clone %d"
          % (o["adiadas"], k["adiadas"]))
    if k["videos"]:
        print("   [aviso] vídeo sem carregar no clone: %d" % len(k["videos"]))

    print("\n-- JAVASCRIPT")
    so_clone = [e for e in k["erros"] if e not in o["erros"]]
    if so_clone:
        problemas.append("%d erro(s) de JS só no clone" % len(so_clone))
        print("   [FALHA] erro que o original não tem:")
        for e in so_clone[:10]:
            print("      %s" % e[:110])
    else:
        print("   [OK] nenhum erro de JS que o original também não tenha")

    print("\n-- CHAMADAS EXTERNAS")
    fora = {d: n for d, n in k["fora"].items()
            if not d.startswith(("http://127.0.0.1", "http://localhost"))}
    # Nem toda chamada externa é vazamento. A da rede de anúncio é; a da
    # API de preços da própria loja é função — tirar ela apaga o preço da
    # tela. As duas aparecem, separadas, e só a primeira reprova.
    rastreio = {d: n for d, n in fora.items() if eh_tracker(d)}
    funcao = {d: n for d, n in fora.items() if d not in rastreio}
    if rastreio:
        problemas.append("%d domínio(s) de rastreamento ainda chamados pelo clone"
                         % len(rastreio))
        print("   [FALHA] o clone telefonou para rastreamento:")
        for d, n in sorted(rastreio.items()):
            print("      %-45s %d" % (d, n))
    else:
        print("   [OK] o clone não telefona para nenhum rastreador")
    if funcao:
        print("   [aviso] chamada externa que NÃO é rastreamento — decida se fica:")
        for d, n in sorted(funcao.items()):
            print("      %-45s %d" % (d, n))
        print("      (para tirar, acrescente o domínio a TRACKER_SRC no clonar.py)")
    print("   (o original chamou %d domínio(s) de fora — é o rastreamento)"
          % len(o["fora"]))

    print("\n-- FORMA DA PÁGINA")
    print("   altura    : original %dpx | clone %dpx" % (o["altura"], k["altura"]))
    print("   elementos : original %d | clone %d" % (o["elementos"], k["elementos"]))

    print()
    if problemas:
        print(">>> %d PROBLEMA(S): %s" % (len(problemas), "; ".join(problemas)))
    else:
        print(">>> CLONE FIEL — pede a mesma mídia, nada quebrado, "
              "nenhum rastreador%s"
              % (" (veja o aviso acima)" if funcao else ""))
    print("=" * 62)
    return problemas


def main():
    ap = argparse.ArgumentParser(
        description="Compara o clone com a página original num Chrome de verdade")
    ap.add_argument("nome", help="nome do clone (pasta em clones/) ou caminho")
    ap.add_argument("--origem", default="",
                    help="URL da página original (padrão: a do .clone.json)")
    ap.add_argument("--porta", type=int, default=9223)
    a = ap.parse_args()
    sys.exit(1 if conferir(a.nome, a.origem, a.porta) else 0)


if __name__ == "__main__":
    main()
