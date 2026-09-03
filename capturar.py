#!/usr/bin/env python3
"""Captura uma página dirigindo um Chrome de verdade — sem colar nada no console.

    ./capturar.py "https://exemplo.com/oferta"
    ./capturar.py "https://exemplo.com/oferta" --clonar meusite --link "<afiliado>" \
                  --idiomas "pt-br,en,de"

Por que um Chrome de verdade e não `curl`: páginas atrás de Cloudflare
respondem 403 para qualquer coisa que não pareça navegador — e VPN não muda
isso, porque a checagem é de fingerprint TLS/HTTP2 e desafio em JS, não de
origem geográfica. A VPN resolve o OUTRO muro, o geobloqueio, e como ela é
de sistema o Chrome herda ela sozinho.

O Chrome usado é um perfil dedicado em ~/.clonador-chrome, separado do seu
navegador do dia a dia. Ele guarda os cookies entre as rodadas, então o
clearance do Cloudflare de um site já visitado é reaproveitado.
"""
import argparse, glob, json, os, shutil, subprocess, sys, time
from urllib.request import urlopen

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)
from cdp import Chrome                                          # noqa: E402
from clonar import diagnostica_pagina                           # noqa: E402
import proxyauth                                                # noqa: E402

PERFIL = os.path.expanduser("~/.clonador-chrome")
PERFIL_ATUAL = PERFIL
PORTA = 9222


def chrome_bin():
    for c in ("google-chrome-stable", "google-chrome", "chromium-browser",
              "chromium", "/opt/google/chrome/chrome"):
        p = shutil.which(c) or (c if os.path.exists(c) else None)
        if p:
            return p
    sys.exit("ERRO: Chrome/Chromium não encontrado.")


def vivo(porta):
    try:
        urlopen("http://127.0.0.1:%d/json/version" % porta, timeout=2).read()
        return True
    except Exception:
        return False


def sobe_xvfb(largura=1440, altura=900):
    """Sobe uma tela virtual e devolve (processo, ":N").

    Xvfb desenha na memória em vez de num monitor. O Chrome que roda em
    cima dele NÃO é headless: é o navegador normal, com janela, renderizando
    de verdade — só que a tela não existe fisicamente. É a diferença que
    importa, porque a detecção olha para os sinais do modo headless
    (navigator.webdriver, HeadlessChrome no user-agent, APIs ausentes), não
    para a existência de um monitor.
    """
    if not shutil.which("Xvfb"):
        sys.exit("ERRO: Xvfb não instalado.  sudo apt install -y xvfb")
    usados = set()
    for f in glob.glob("/tmp/.X11-unix/X*"):
        try:
            usados.add(int(os.path.basename(f)[1:]))
        except ValueError:
            pass
    n = next(i for i in range(90, 200) if i not in usados)
    p = subprocess.Popen(
        ["Xvfb", ":%d" % n, "-screen", "0", "%dx%dx24" % (largura, altura),
         "-nolisten", "tcp"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        if os.path.exists("/tmp/.X11-unix/X%d" % n):
            print("xvfb   : tela virtual :%d (%dx%d)" % (n, largura, altura))
            return p, ":%d" % n
        time.sleep(0.25)
    p.terminate()
    sys.exit("ERRO: Xvfb não subiu.")


def sobe_chrome(porta, visivel, display=None, proxy=""):
    if vivo(porta):
        print("chrome : já rodando na porta %d" % porta)
        return None
    os.makedirs(PERFIL_ATUAL, exist_ok=True)
    args = [chrome_bin(),
            "--remote-debugging-port=%d" % porta,
            "--user-data-dir=" + PERFIL_ATUAL,
            "--no-first-run", "--no-default-browser-check",
            "--disable-features=Translate,MediaRouter",
            "--window-size=1440,900"]
    if proxy:
        args.append("--proxy-server=" + proxy)
    if not visivel:
        args.append("--headless=new")
    env = dict(os.environ)
    if display:
        env["DISPLAY"] = display
        env.pop("WAYLAND_DISPLAY", None)     # senão o Chrome ignora o X
    p = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, env=env)
    for _ in range(60):
        if vivo(porta):
            print("chrome : subiu%s (perfil %s)"
                  % (" com janela em tela virtual" if display else
                     ("" if visivel else " em headless"), PERFIL_ATUAL))
            return p
        time.sleep(0.5)
    # A causa quase sempre é outra janela do Chrome segurando o perfil: o
    # Chrome recusa abrir uma segunda instância nele, e a porta nunca sobe.
    lock = os.path.join(PERFIL_ATUAL, "SingletonLock")
    dono = ""
    if os.path.islink(lock):
        dono = os.readlink(lock)
    raise RuntimeError(
        "o Chrome não abriu a porta de depuração %d.\n"
        "       %s"
        % (porta,
           ("Há uma janela do Chrome usando este perfil (%s) — "
            "provavelmente a\n       que você abriu para configurar a VPN. "
            "FECHE ela e rode de novo.\n"
            "       (a partir de agora a janela de configuração já sobe com "
            "a porta aberta,\n       então isso não volta a acontecer)" % dono)
           if dono else
           "Perfil: %s — verifique se o Chrome consegue abrir." % PERFIL_ATUAL))


def configurar(porta=PORTA, url="https://www.google.com/"):
    """Abre o perfil da automação como um navegador comum, para você
    instalar a VPN e entrar na conta dela.

    A automação usa um perfil próprio (~/.clonador-chrome), separado do seu
    Chrome do dia a dia. Uma extensão de VPN vive DENTRO do perfil: por isso
    a que está no seu navegador não aparece aqui. Instale nele uma vez e
    todas as capturas seguintes saem por ela — o perfil é permanente.
    """
    os.makedirs(PERFIL, exist_ok=True)
    print("Abrindo o navegador da automação (perfil %s).\n" % PERFIL)
    print("  1. Instale a extensão da sua VPN e faça login")
    print("  2. Ligue a VPN e confira o país")
    print("  3. FECHE a janela — a configuração fica salva\n")
    # Sobe já com a porta de depuração: assim, se você deixar esta janela
    # aberta, a captura ATTACHA nela em vez de esbarrar no lock do perfil.
    # Sem isso, esquecer a janela aberta travava toda captura seguinte com
    # "o Chrome não abriu a porta de depuração".
    p = subprocess.Popen(
        [chrome_bin(), "--user-data-dir=" + PERFIL,
         "--remote-debugging-port=%d" % porta,
         "--no-first-run", "--no-default-browser-check",
         "--window-size=1280,860", url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    p.wait()
    ext = os.path.join(PERFIL, "Default", "Extensions")
    n = len(os.listdir(ext)) if os.path.isdir(ext) else 0
    print("pronto: %d extensão(ões) no perfil da automação." % n)
    if not n:
        print("        Nenhuma instalada — a captura vai sair pelo seu IP normal.")
    return n


def ip_visto(c, sess):
    """De que IP o navegador da automação está saindo (confere a VPN).

    Navega até o serviço em vez de fazer fetch: de about:blank o fetch é
    bloqueado por origem opaca, e de dentro da página-alvo esbarraria no
    CORS/CSP dela.
    """
    # ipapi.co fica atrás do próprio Cloudflare e devolve página de
    # verificação; estes respondem JSON direto. Vai em cascata.
    for u in ("https://ipinfo.io/json", "https://ifconfig.co/json",
              "https://api.ipify.org/?format=json"):
        try:
            c.cmd("Page.navigate", {"url": u}, sessao=sess, espera=60)
            c.eventos_ate("Page.loadEventFired", espera=25)
            time.sleep(0.6)
            r = c.cmd("Runtime.evaluate",
                      {"expression": "document.body?document.body.innerText:''",
                       "returnByValue": True},
                      sessao=sess, espera=25).get("result", {}).get("value", "")
            i, f = r.find("{"), r.rfind("}")
            if i < 0 or f <= i:
                continue
            j = json.loads(r[i:f + 1])
            if not j.get("ip"):
                continue
            return {"ip": j["ip"],
                    "pais": j.get("country_iso") or j.get("country") or "",
                    "cc": j.get("country") or ""}
        except Exception:
            continue
    return {}


def capturar(url, destino, porta=PORTA, visivel=False, espera=900, rolagem=25,
             perfil=None, xvfb=False, proxy="", conferir_ip=False,
             mesmo_assim=False, pais=""):
    global PERFIL_ATUAL
    PERFIL_ATUAL = perfil or PERFIL
    os.makedirs(destino, exist_ok=True)
    antes = set(glob.glob(os.path.join(destino, "*.json")))
    # Proxy com usuário/senha: o Chrome não aceita credencial na flag, então
    # sobe um encaminhador local sem senha e aponta o navegador para ele.
    proxy_chrome, encaminhador = proxyauth.prepara(proxy)
    if encaminhador:
        print("proxy  : encaminhador local em %s -> %s"
              % (encaminhador.endereco, proxy.split("@")[-1]))
    elif proxy:
        print("proxy  : %s" % proxy)

    xproc, display = (None, None)
    if xvfb:
        xproc, display = sobe_xvfb()
        visivel = True                      # sob Xvfb o Chrome roda com janela
    try:
        proc = sobe_chrome(porta, visivel, display, proxy_chrome)
    except BaseException:
        if xproc:
            xproc.terminate()               # senão a tela virtual fica órfã
        if encaminhador:
            encaminhador.encerrar()
        raise
    c = Chrome(porta)
    print("chrome : %s" % c.versao)
    alvo = c.cmd("Target.createTarget", {"url": "about:blank"})["targetId"]
    sess = c.cmd("Target.attachToTarget",
                 {"targetId": alvo, "flatten": True})["sessionId"]
    try:
        # o .json da captura é grande demais para voltar pelo WebSocket:
        # deixamos o próprio download da página cair numa pasta nossa.
        c.cmd("Browser.setDownloadBehavior",
              {"behavior": "allow", "downloadPath": destino, "eventsEnabled": True})
        c.cmd("Page.enable", sessao=sess)
        c.cmd("Runtime.enable", sessao=sess)
        if conferir_ip or pais:
            i = ip_visto(c, sess)
            cc = (i.get("pais") or i.get("cc") or "").upper()
            if i.get("ip"):
                print("saindo : %s  (%s)%s"
                      % (i["ip"], cc or "?",
                         "" if pais else "  <- confira se é o país da sua VPN"))
            else:
                print("saindo : não deu para conferir o IP")
            # Com --pais, a saída errada para ANTES da captura: clonar de um
            # país que não é o do funil traz a página errada, ou nenhuma.
            if pais:
                esperado = pais.strip().upper()
                if not cc:
                    raise RuntimeError(
                        "não deu para conferir o país de saída, e você pediu "
                        "%s.\n       Rode sem --pais para capturar assim mesmo."
                        % esperado)
                if cc != esperado:
                    raise RuntimeError(
                        "saindo pelo país errado: %s, e você pediu %s.\n"
                        "       A VPN não está ativa nesta sessão do "
                        "navegador.\n"
                        "       VPN de extensão costuma precisar de clique em "
                        "'conectar' a cada sessão —\n"
                        "       por isso VPN de sistema (WireGuard/OpenVPN) ou "
                        "--proxy resolvem de vez."
                        % (cc, esperado))
        print("abrindo: %s" % url)
        c.cmd("Page.navigate", {"url": url}, sessao=sess, espera=120)
        c.eventos_ate("Page.loadEventFired", espera=90)
        time.sleep(3)                       # deixa o JS da página assentar

        titulo = c.cmd("Runtime.evaluate",
                       {"expression": "document.title", "returnByValue": True},
                       sessao=sess).get("result", {}).get("value", "")
        # Desafio do Cloudflare tem assinatura própria no DOM — usar só
        # "a página está curta" daria falso positivo em qualquer página enxuta.
        sonda = ("(function(){var b=document.body;return JSON.stringify({"
                 "txt:b?b.innerText.length:0,"
                 "res:performance.getEntriesByType('resource').length,"
                 "texto:b?b.innerText.slice(0,3000):'',"
                 "chl:!!(document.querySelector('#challenge-form,#cf-challenge-running,"
                 "[class*=cf-browser-verification],[id^=cf-chl],#turnstile-wrapper')"
                 "||/just a moment|checking your browser|verifying you are human"
                 "|um momento|verificando/i.test(document.title+' '+(b?b.innerText.slice(0,400):'')))"
                 "});})()")
        info = json.loads(c.cmd("Runtime.evaluate",
                                {"expression": sonda, "returnByValue": True},
                                sessao=sess).get("result", {}).get("value", "{}"))
        print("página : %r (%d caracteres, %d recursos)"
              % (titulo, info.get("txt", 0), info.get("res", 0)))

        # Não adianta capturar uma tela de erro: sem isto o clonador
        # empacotava a página de bloqueio no lugar do site.
        corpo = c.cmd("Runtime.evaluate",
                      {"expression": "document.documentElement.outerHTML",
                       "returnByValue": True},
                      sessao=sess).get("result", {}).get("value", "") or ""
        sit, motivo = diagnostica_pagina(corpo, titulo, info.get("texto", ""),
                                         info.get("res", 0))
        if sit != "ok" and not mesmo_assim:
            if sit == "bloqueado":
                raise RuntimeError(
                    "a página não abriu: o site BLOQUEOU o acesso (%r).\n"
                    "       Isso é a rede recusando seu IP — janela ou tela "
                    "virtual não mudam nada.\n"
                    "       Saídas: ligar a VPN no perfil da automação "
                    "(capturar.py --configurar),\n"
                    "       usar --proxy, ou tentar de outra rede. "
                    "--mesmo-assim captura do jeito que está." % motivo)
            raise RuntimeError(
                "a página não abriu: parou num DESAFIO do Cloudflare (%r).\n"
                "       Rode com --visivel e passe por ele na tela uma vez; o "
                "cookie fica salvo\n"
                "       em %s e as próximas rodadas desse site passam "
                "sozinhas.\n"
                "       --mesmo-assim captura do jeito que está."
                % (motivo, PERFIL))

        js = open(os.path.join(RAIZ, "capturar.js"), encoding="utf-8").read()
        print("captura: rodando capturar.js na página (rola tudo e baixa os assets)")
        c.cmd("Runtime.evaluate",
              {"expression": js, "awaitPromise": False, "userGesture": True},
              sessao=sess)

        fim, ultimo = time.time() + espera, None
        while time.time() < fim:
            time.sleep(2)
            novos = [f for f in glob.glob(os.path.join(destino, "*.json"))
                     if f not in antes]
            parciais = glob.glob(os.path.join(destino, "*.crdownload"))
            if novos and not parciais:
                t1, t2 = os.path.getsize(novos[0]), None
                time.sleep(1.5)
                t2 = os.path.getsize(novos[0])
                if t1 == t2 and t1 > 0:
                    print("pronto : %s (%.1f MB)" % (novos[0], t1 / 1048576.0))
                    return novos[0]
            if parciais and parciais[0] != ultimo:
                ultimo = parciais[0]
                print("        baixando…")
        raise TimeoutError("a captura não terminou em %ds" % espera)
    finally:
        try:
            c.cmd("Target.closeTarget", {"targetId": alvo})
        except Exception:
            pass
        c.fechar()
        if proc:
            proc.terminate()
        if xproc:
            xproc.terminate()
        if encaminhador:
            encaminhador.encerrar()


def main():
    ap = argparse.ArgumentParser(
        description="Captura uma página com um Chrome de verdade, sem colar nada")
    ap.add_argument("url", nargs="?", default="",
                    help="link da página (dispensável com --configurar)")
    ap.add_argument("--saida", default=os.path.expanduser("~/Downloads"),
                    help="onde o .json da captura cai (padrão ~/Downloads)")
    ap.add_argument("--porta", type=int, default=PORTA)
    ap.add_argument("--perfil", default="",
                    help="pasta de perfil do Chrome (padrão ~/.clonador-chrome). "
                         "Um perfil novo começa sem os cookies do Cloudflare.")
    ap.add_argument("--configurar", action="store_true",
                    help="abre o navegador da automação para você instalar a "
                         "VPN e logar nela; a configuração fica salva no perfil")
    ap.add_argument("--proxy", default="", metavar="URL",
                    help="manda o Chrome sair por um proxy. Aceita usuário e senha: "
                         "http://user:senha@host:porta — ou socks5://host:porta")
    ap.add_argument("--mesmo-assim", action="store_true",
                    help="captura mesmo que a página seja um bloqueio ou "
                         "desafio (o padrão é parar e explicar)")
    ap.add_argument("--pais", default="", metavar="XX",
                    help="só captura se o navegador estiver saindo por este "
                         "país (ex.: US). Para antes se a VPN não estiver ativa.")
    ap.add_argument("--conferir-ip", action="store_true",
                    help="mostra de que IP/país o navegador está saindo")
    ap.add_argument("--xvfb", action="store_true",
                    help="roda o Chrome COM janela numa tela virtual (Xvfb). "
                         "É o modo para servidor sem monitor: não é headless, "
                         "então não dispara a detecção que o headless dispara.")
    ap.add_argument("--visivel", action="store_true",
                    help="abre o Chrome na tela (para resolver desafio à mão)")
    ap.add_argument("--espera", type=int, default=900,
                    help="segundos de paciência com a captura (padrão 900)")
    ap.add_argument("--clonar", metavar="NOME",
                    help="já monta o clone com esse nome ao terminar")
    ap.add_argument("--link", default="", help="link de afiliado, para o --clonar")
    ap.add_argument("--idiomas", default="", help="idiomas, para o --clonar")
    a = ap.parse_args()
    if a.configurar:
        configurar(a.porta)
        return
    if not a.url:
        sys.exit("ERRO: faltou o link da página.")

    try:
        arq = capturar(a.url, a.saida, a.porta, a.visivel, a.espera,
                       perfil=a.perfil or None, xvfb=a.xvfb,
                       proxy=a.proxy, conferir_ip=a.conferir_ip,
                       mesmo_assim=a.mesmo_assim, pais=a.pais)
    except (RuntimeError, TimeoutError) as e:
        # erro esperado (bloqueio, desafio, tempo): mensagem, não traceback
        sys.exit("ERRO: %s" % e)
    if a.clonar:
        cmd = [sys.executable, os.path.join(RAIZ, "clonar.py"), arq, a.clonar]
        if a.link:
            cmd += ["--link", a.link]
        if a.idiomas:
            cmd += ["--idiomas", a.idiomas]
        print("\n" + " ".join(cmd) + "\n")
        sys.exit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
