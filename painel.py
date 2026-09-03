#!/usr/bin/env python3
"""echopage — painel local do clonador.

    ./painel.py            →  http://localhost:7000

Um formulário com o link do site e o link de afiliado. O painel roda a
rotina inteira — captura no Chrome, limpeza, idiomas — mostrando o log ao
vivo, e serve o clone pronto no mesmo endereço.
"""
import html as _html
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RAIZ = os.path.dirname(os.path.abspath(__file__))
CLONES = os.path.join(RAIZ, "clones")
CAPTURAS = os.path.join(RAIZ, ".capturas")
ZIPS = os.path.join(RAIZ, ".zips")
PORTA = 7000

MIME = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".json": "application/json",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".avif": "image/avif",
    ".svg": "image/svg+xml", ".ico": "image/x-icon",
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm",
    ".ogg": "audio/ogg", ".mp3": "audio/mpeg",
    ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf",
    ".otf": "font/otf", ".eot": "application/vnd.ms-fontobject",
}

tarefas = {}
trava = threading.Lock()


def nome_de(url):
    h = urllib.parse.urlsplit(url).hostname or "site"
    h = re.sub(r"^www\.", "", h)
    return re.sub(r"[^a-z0-9]+", "-", h.lower()).strip("-") or "site"


def lista_clones():
    saida = []
    if not os.path.isdir(CLONES):
        return saida
    for d in sorted(os.listdir(CLONES)):
        cam = os.path.join(CLONES, d)
        if not os.path.isdir(cam) or not os.path.exists(os.path.join(cam, "index.html")):
            continue
        bytes_ = 0
        for r, _, fs in os.walk(cam):
            for f in fs:
                try:
                    bytes_ += os.path.getsize(os.path.join(r, f))
                except OSError:
                    pass
        idiomas = []
        dj = os.path.join(cam, "i18n", "dicionarios.js")
        if os.path.exists(dj):
            try:
                t = io.open(dj, encoding="utf-8").read()
                idiomas = json.loads(t[t.index("{"):t.index(";\nwindow.__CLONE_I18N_ADD")])\
                    .get("codigos", [])
            except Exception:
                pass
        ficha = {}
        fj = os.path.join(cam, ".clone.json")
        if os.path.exists(fj):
            try:
                ficha = json.load(io.open(fj, encoding="utf-8"))
            except Exception:
                ficha = {}
        saida.append({"nome": d, "mb": round(bytes_ / 1048576.0, 1),
                      "idiomas": idiomas,
                      "origem": ficha.get("origem", ""),
                      "link": ficha.get("link_afiliado", ""),
                      "quando": (ficha.get("quando", "") or time.strftime(
                          "%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(
                              os.path.join(cam, "index.html")))))[5:16]})
    return saida


def roda(tid, url, link, visivel, proxy="", conferir=True):
    t = tarefas[tid]

    def diz(linha, tipo="log"):
        t["linhas"].append((tipo, linha))
        t["acordar"].set()

    def executa(cmd, rotulo):
        diz(rotulo, "etapa")
        diz("$ " + " ".join(cmd[1:]), "cmd")
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, bufsize=1, cwd=RAIZ,
                             stdin=subprocess.DEVNULL)
        t["proc"] = p
        for linha in p.stdout:
            diz(linha.rstrip("\n"))
        p.wait()
        return p.returncode

    try:
        nome = nome_de(url)
        t["nome"] = nome
        os.makedirs(CAPTURAS, exist_ok=True)
        destino = os.path.join(CAPTURAS, nome)
        shutil.rmtree(destino, ignore_errors=True)
        os.makedirs(destino, exist_ok=True)

        cmd = [sys.executable, os.path.join(RAIZ, "capturar.py"), url,
               "--saida", destino, "--espera", "900"]
        cmd.append("--visivel" if visivel else "--xvfb")
        if proxy:
            cmd += ["--proxy", proxy]
        if conferir:
            cmd.append("--conferir-ip")
        if executa(cmd, "1/2 · Capturando a página no Chrome") != 0:
            raise RuntimeError("a captura falhou")

        jsons = [os.path.join(destino, f) for f in os.listdir(destino)
                 if f.endswith(".json")]
        if not jsons:
            raise RuntimeError("a captura não gerou arquivo")
        arq = max(jsons, key=os.path.getsize)

        cmd = [sys.executable, os.path.join(RAIZ, "clonar.py"), arq, nome, "--offline"]
        if link:
            cmd += ["--link", link]
        if executa(cmd, "2/2 · Limpando, removendo tracking e montando") != 0:
            raise RuntimeError("a montagem falhou")

        shutil.rmtree(destino, ignore_errors=True)
        t["estado"] = "pronto"
        diz("/c/%s/" % nome, "pronto")
    except Exception as e:
        t["estado"] = "erro"
        diz(str(e), "erro")
    finally:
        t["fim"] = True
        t["acordar"].set()


PAGINA = r"""<!doctype html><html lang=pt-br><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>echopage</title>
<link rel=icon href="data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 24 24%27 fill=%27none%27%3E%3Crect x=%277.4%27 y=%272.6%27 width=%2714%27 height=%2714%27 rx=%273.4%27 stroke=%27white%27 stroke-opacity=%27.35%27 stroke-width=%272%27/%3E%3Crect x=%272.6%27 y=%277.4%27 width=%2714%27 height=%2714%27 rx=%273.4%27 fill=%27%230d0e10%27 stroke=%27white%27 stroke-width=%272%27/%3E%3Cpath d=%27M6.3 12.4h6.6M6.3 16.1h4.1%27 stroke=%27white%27 stroke-width=%272%27 stroke-linecap=%27round%27/%3E%3C/svg%3E">
<style>
:root{
 --fundo:#0d0e10; --fundo2:#111214;
 --cartao:#16181b; --cartao2:#1b1e22;
 --linha:#24272c; --linha2:#2f333a;
 --txt:#e7e9ec; --fraco:#8b9097; --fraco2:#666b73;
 --branco:#fff;
 --ok:#6ee7a8; --aviso:#f0c674; --erro:#f0908d; --info:#8ab4f8;
 --raio:12px;
}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:var(--fundo);color:var(--txt);
 font:14.5px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Inter,sans-serif;
 -webkit-font-smoothing:antialiased;
 background-image:radial-gradient(900px 420px at 50% -180px,#1a1d21 0%,transparent 70%)}
.wrap{max-width:860px;margin:0 auto;padding:34px 20px 80px}

/* ── marca ───────────────────────────────────────────── */
.topo{display:flex;align-items:center;gap:14px;margin:0 0 9px}
.glifo{flex:0 0 auto}
.nome{font-family:ui-monospace,"SF Mono","JetBrains Mono","IBM Plex Mono",
 "Cascadia Code",Menlo,Consolas,monospace;
 font-size:31px;font-weight:600;letter-spacing:-.042em;color:var(--branco);
 line-height:1}
.nome b{font-weight:700}
.sub{color:var(--fraco);font-size:13.5px;margin:0 0 32px;padding-left:50px}

/* ── cartões ─────────────────────────────────────────── */
.cartao{background:var(--cartao);border:1px solid var(--linha);
 border-radius:var(--raio);padding:20px}
.cartao+.cartao{margin-top:14px}
.titulo{font-size:11px;font-weight:700;letter-spacing:.09em;
 text-transform:uppercase;color:var(--fraco2);margin:0 0 14px}

/* ── formulário ──────────────────────────────────────── */
.campo{margin-bottom:15px}
label{display:block;font-size:12.5px;font-weight:600;margin:0 0 6px;color:var(--txt)}
.dica{color:var(--fraco);font-weight:400}
input[type=url],input[type=text]{width:100%;padding:11px 13px;
 border:1px solid var(--linha2);border-radius:9px;background:var(--fundo2);
 color:var(--txt);font:inherit;font-size:14px;transition:border-color .15s}
input::placeholder{color:var(--fraco2)}
input:focus{outline:none;border-color:#4a5560;background:#0f1113}

.linha{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin-top:4px}
button{padding:11px 20px;border:0;border-radius:9px;background:var(--branco);
 color:#0d0e10;font:inherit;font-weight:650;font-size:14px;cursor:pointer;
 transition:opacity .15s,transform .1s}
button:hover:not(:disabled){opacity:.88}
button:active:not(:disabled){transform:translateY(1px)}
button:disabled{opacity:.4;cursor:default}
button.sec{background:transparent;color:var(--txt);border:1px solid var(--linha2);
 font-weight:600;font-size:13px;padding:9px 15px}
button.sec:hover:not(:disabled){border-color:#454b53;background:var(--cartao2)}
.check{display:flex;gap:8px;align-items:center;font-size:13px;color:var(--fraco);
 cursor:pointer;user-select:none}
.check input{accent-color:#8b9097;width:15px;height:15px;cursor:pointer}

/* ── aviso ───────────────────────────────────────────── */
.aviso{border:1px solid var(--linha2);border-left:2px solid var(--aviso);
 border-radius:9px;padding:13px 15px;margin:16px 0;font-size:13px;
 color:var(--fraco);background:var(--fundo2)}
.aviso b{color:var(--txt);font-weight:600}
.aviso ul{margin:9px 0 0;padding-left:17px}
.aviso li{margin:4px 0}
code{font-family:ui-monospace,Menlo,monospace;font-size:12px;
 background:var(--cartao2);padding:1px 5px;border-radius:4px;color:var(--txt)}

/* ── avançado ────────────────────────────────────────── */
details{border:1px solid var(--linha);border-radius:9px;padding:0;
 margin:0 0 16px;background:var(--fundo2);overflow:hidden}
summary{cursor:pointer;font-size:13px;font-weight:600;padding:11px 15px;
 list-style:none;color:var(--fraco);transition:color .15s}
summary::-webkit-details-marker{display:none}
summary:before{content:"+";display:inline-block;width:14px;color:var(--fraco2);
 font-weight:700}
details[open] summary{color:var(--txt);border-bottom:1px solid var(--linha)}
details[open] summary:before{content:"−"}
.corpo{padding:15px}
.dica2{color:var(--fraco);font-size:12.5px;margin:0 0 12px;line-height:1.6}

/* ── log ─────────────────────────────────────────────── */
#log{background:#0a0b0c;border:1px solid var(--linha);border-radius:var(--raio);
 padding:16px;margin-top:14px;
 font:12.5px/1.65 ui-monospace,"SF Mono",Menlo,Consolas,monospace;
 max-height:420px;overflow:auto;white-space:pre-wrap;word-break:break-word;
 color:#b6bcc4}
#log:empty{display:none}
#log::-webkit-scrollbar{width:9px}
#log::-webkit-scrollbar-thumb{background:#2b2f35;border-radius:5px}
.etapa{color:var(--branco);font-weight:700;display:block;margin:12px 0 5px;
 letter-spacing:.01em}
.etapa:first-child{margin-top:0}
.cmd{color:var(--fraco2)}
.erro{color:var(--erro);font-weight:600}
.ok{color:var(--ok);font-weight:700}
.saindo{color:var(--aviso)}
.feito{display:flex;gap:10px;align-items:center;margin:12px 0 2px;flex-wrap:wrap}

/* ── tabela ──────────────────────────────────────────── */
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{text-align:left;padding:0 8px 9px;font-size:10.5px;color:var(--fraco2);
 font-weight:700;text-transform:uppercase;letter-spacing:.08em;
 border-bottom:1px solid var(--linha)}
td{padding:11px 8px;border-bottom:1px solid var(--linha)}
tr:last-child td{border-bottom:0}
tbody tr:hover{background:var(--cartao2)}
a{color:var(--info);text-decoration:none}
a:hover{text-decoration:underline}
.org{color:var(--fraco);font-size:11.5px;
 font-family:ui-monospace,Menlo,monospace}
.tag{display:inline-block;background:var(--fundo2);border:1px solid var(--linha2);
 border-radius:4px;padding:1px 5px;font-size:10.5px;color:var(--fraco);
 margin:1px 2px 1px 0;font-family:ui-monospace,Menlo,monospace}
.zip{display:inline-block;padding:6px 12px;border:1px solid var(--linha2);
 border-radius:7px;background:transparent;color:var(--txt);
 font-size:12px;font-weight:600;white-space:nowrap;text-decoration:none}
.zip:hover{border-color:#454b53;background:var(--cartao2);text-decoration:none}
.vazio{color:var(--fraco2);font-size:13.5px;margin:4px 0 0}
.num{color:var(--fraco);font-variant-numeric:tabular-nums}

@media (max-width:560px){
 .wrap{padding:24px 14px 60px}
 .nome{font-size:26px}
 .glifo{width:30px;height:30px}
 .sub{padding-left:0}
 th:nth-child(2),td:nth-child(2),th:nth-child(4),td:nth-child(4){display:none}
}
</style></head><body><div class=wrap>

<div class=topo>
 <svg class=glifo width="36" height="36" viewBox="0 0 24 24" fill="none">
  <rect x="7.4" y="2.6" width="14" height="14" rx="3.4"
        stroke="#fff" stroke-opacity=".3" stroke-width="1.7"/>
  <rect x="2.6" y="7.4" width="14" height="14" rx="3.4"
        fill="#0d0e10" stroke="#fff" stroke-width="1.7"/>
  <path d="M6.3 12.4h6.6M6.3 16.1h4.1" stroke="#fff"
        stroke-width="1.7" stroke-linecap="round"/>
 </svg>
 <span class=nome>echo<b>page</b></span>
</div>
<p class=sub>Clona a página, remove o rastreamento e aponta tudo para o seu link.</p>

<div class=cartao>
 <form id=f>
  <div class=campo>
   <label for=url>Link da página <span class=dica>— o site que você quer clonar</span></label>
   <input id=url type=url required placeholder="https://exemplo.com/oferta">
  </div>
  <div class=campo>
   <label for=link>Seu link de afiliado <span class=dica>— para onde todo botão vai levar</span></label>
   <input id=link type=url placeholder="https://rede.com/ABC123/?uid=000">
  </div>

  <details>
   <summary>VPN e proxy</summary>
   <div class=corpo>
    <p class=dica2>A automação usa um perfil próprio de Chrome, separado do seu.
     Uma extensão de VPN vive <b>dentro</b> do perfil — por isso a que está no
     seu navegador não aparece aqui. Configure uma vez e vale para todas as capturas.</p>
    <button type=button id=cfg class=sec>Configurar VPN no navegador da automação</button>
    <p class=dica2 style="margin:10px 0 0">Abre uma janela. Instale a extensão,
     faça login, ligue a VPN e feche a janela — fica salvo.</p>
    <div class=campo style="margin:16px 0 0">
     <label for=proxy>Ou um proxy <span class=dica>— aceita usuário e senha</span></label>
     <input id=proxy type=text placeholder="http://usuario:senha@host:8080">
    </div>
   </div>
  </details>

  <div class=aviso>
   <b>Antes de começar:</b> isto abre um Chrome de verdade na sua máquina.
   <ul>
    <li>É necessário: páginas atrás de Cloudflare recusam o que não é navegador.</li>
    <li>Por padrão ele roda numa tela virtual — nada aparece no seu monitor.</li>
    <li>O perfil fica em <code>~/.clonador-chrome</code>, separado do seu Chrome.</li>
    <li>Leva de 2 a 8 minutos, conforme o peso das imagens e vídeos.</li>
    <li>No fim você abre no navegador ou baixa o <b>.zip</b>, que funciona offline.</li>
   </ul>
  </div>

  <div class=linha>
   <button id=b type=submit>Clonar</button>
   <label class=check><input id=vis type=checkbox> abrir o Chrome na tela</label>
   <label class=check><input id=cip type=checkbox checked> conferir o IP de saída</label>
  </div>
 </form>
</div>

<div id=log></div>

<div class=cartao style="margin-top:14px">
 <p class=titulo>Clones</p>
 <table><thead><tr><th>Nome</th><th>Origem</th><th>Idiomas</th><th>Tamanho</th><th>Feito em</th><th></th></tr></thead>
 <tbody id=lista></tbody></table>
 <p class=vazio id=vazio hidden>Nenhum clone ainda.</p>
</div>

</div><script>
const $=s=>document.querySelector(s), log=$('#log');
function add(t,c){const e=document.createElement('span');
 if(c)e.className=c; e.textContent=t+'\n'; log.appendChild(e); log.scrollTop=log.scrollHeight;}
async function lista(){
 const r=await fetch('/api/clones'), cs=await r.json();
 const tb=$('#lista'); tb.innerHTML='';
 $('#vazio').hidden=cs.length>0;
 for(const c of cs){
  const tr=document.createElement('tr');
  const idi=c.idiomas.length?c.idiomas.slice(0,6).map(x=>'<span class=tag>'+x+'</span>').join('')+
   (c.idiomas.length>6?'<span class=tag>+'+(c.idiomas.length-6)+'</span>':''):'<span class=tag>—</span>';
  const org=c.origem?('<span class=org title="'+c.origem+'">'+
   c.origem.replace(/^https?:\/\//,'').slice(0,34)+'</span>'):'<span class=org>—</span>';
  tr.innerHTML='<td><a href="/c/'+c.nome+'/" target=_blank>'+c.nome+'</a></td>'+
   '<td>'+org+'</td><td>'+idi+'</td><td class=num>'+c.mb+' MB</td>'+
   '<td class=num>'+c.quando+'</td>'+
   '<td><a class=zip href="/api/zip?nome='+c.nome+'">baixar .zip</a></td>';
  tb.appendChild(tr);
 }
}
$('#f').addEventListener('submit',async e=>{
 e.preventDefault(); $('#b').disabled=true; $('#b').textContent='Clonando…';
 log.textContent='';
 const r=await fetch('/api/clonar',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({url:$('#url').value,link:$('#link').value,
   visivel:$('#vis').checked,proxy:$('#proxy').value,conferir:$('#cip').checked})});
 const {id}=await r.json();
 const es=new EventSource('/api/log?id='+id);
 es.onmessage=ev=>{
  const m=JSON.parse(ev.data);
  if(m.tipo==='fim'){es.close();$('#b').disabled=false;$('#b').textContent='Clonar';lista();return;}
  if(m.tipo==='pronto'){
   const nome=m.texto.replace(/^\/c\/|\/$/g,'');
   add(''); add('PRONTO','ok');
   const d=document.createElement('div');d.className='feito';
   d.innerHTML='<a class=zip href="'+m.texto+'" target=_blank>abrir no navegador</a>'+
    '<a class=zip href="/api/zip?nome='+nome+'">baixar .zip</a>';
   log.appendChild(d);return;}
  add(m.texto,m.tipo==='etapa'?'etapa':m.tipo==='cmd'?'cmd':m.tipo==='erro'?'erro':
   /^saindo /.test(m.texto)?'saindo':'');
 };
});
$('#cfg').addEventListener('click',async()=>{
 $('#cfg').disabled=true; $('#cfg').textContent='abrindo o navegador…';
 await fetch('/api/configurar',{method:'POST'});
 setTimeout(()=>{$('#cfg').disabled=false;
  $('#cfg').textContent='Configurar VPN no navegador da automação';},4000);
});
lista();
</script></body></html>"""


class Painel(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _envia(self, corpo, tipo="text/html; charset=utf-8", codigo=200):
        if isinstance(corpo, str):
            corpo = corpo.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        cam = urllib.parse.urlsplit(self.path)
        if cam.path == "/":
            return self._envia(PAGINA)
        if cam.path == "/api/clones":
            return self._envia(json.dumps(lista_clones()), "application/json")
        if cam.path == "/api/log":
            return self._sse(urllib.parse.parse_qs(cam.query).get("id", [""])[0])
        if cam.path == "/api/zip":
            n = urllib.parse.parse_qs(cam.query).get("nome", [""])[0]
            return self._zip(re.sub(r"[^A-Za-z0-9._-]", "", n))
        if cam.path.startswith("/c/"):
            return self._clone(urllib.parse.unquote(cam.path[3:]))
        self._envia("não encontrado", "text/plain; charset=utf-8", 404)

    def _sse(self, tid):
        t = tarefas.get(tid)
        if not t:
            return self._envia("sem tarefa", "text/plain", 404)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        i = 0
        try:
            while True:
                while i < len(t["linhas"]):
                    self._evento(*t["linhas"][i])
                    i += 1
                if t["fim"]:
                    self._evento("fim", "")
                    break
                t["acordar"].wait(0.4)
                t["acordar"].clear()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _evento(self, tipo, texto):
        self.wfile.write(("data: %s\n\n" % json.dumps(
            {"tipo": tipo, "texto": texto})).encode("utf-8"))
        self.wfile.flush()

    def _configurar(self):
        subprocess.Popen([sys.executable, os.path.join(RAIZ, "capturar.py"),
                          "--configurar"], cwd=RAIZ,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL)
        self._envia('{"ok":true}', "application/json")

    def _zip(self, nome):
        base = os.path.realpath(os.path.join(CLONES, nome))
        if not base.startswith(os.path.realpath(CLONES) + os.sep) or \
                not os.path.isdir(base):
            return self._envia("não encontrado", "text/plain; charset=utf-8", 404)
        os.makedirs(ZIPS, exist_ok=True)
        alvo = os.path.join(ZIPS, nome + ".zip")
        # o clone muda pouco e pesa dezenas de MB: só reempacota quando
        # algum arquivo dele for mais novo que o zip
        recente = max((os.path.getmtime(os.path.join(r, f))
                       for r, _, fs in os.walk(base) for f in fs), default=0)
        if not os.path.exists(alvo) or os.path.getmtime(alvo) < recente:
            tmp = alvo + ".parcial"
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED,
                                 compresslevel=1) as z:
                for r, _, fs in os.walk(base):
                    for f in fs:
                        if f == ".clone.json":
                            continue      # ficha é nossa, não vai na entrega
                        cheio = os.path.join(r, f)
                        z.write(cheio, os.path.join(
                            nome, os.path.relpath(cheio, base)))
            os.replace(tmp, alvo)
        tam = os.path.getsize(alvo)
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(tam))
        self.send_header("Content-Disposition",
                         'attachment; filename="%s.zip"' % nome)
        self.end_headers()
        with open(alvo, "rb") as f:
            shutil.copyfileobj(f, self.wfile, 1024 * 256)

    def _clone(self, rel):
        partes = rel.split("/", 1)
        nome = partes[0]
        resto = partes[1] if len(partes) > 1 else ""
        base = os.path.realpath(os.path.join(CLONES, nome))
        if not base.startswith(os.path.realpath(CLONES) + os.sep):
            return self._envia("caminho inválido", "text/plain", 403)
        if not resto or resto.endswith("/"):
            resto += "index.html"
        arq = os.path.realpath(os.path.join(base, resto))
        if not arq.startswith(base + os.sep) or not os.path.isfile(arq):
            return self._envia("não encontrado", "text/plain; charset=utf-8", 404)
        ext = os.path.splitext(arq)[1].lower()
        with open(arq, "rb") as f:
            corpo = f.read()
        # extensão desconhecida vira text/plain, nunca octet-stream: o
        # navegador BAIXARIA o arquivo em vez de ignorá-lo
        self._envia(corpo, MIME.get(ext, "text/plain; charset=utf-8"))

    def do_POST(self):
        rota = urllib.parse.urlsplit(self.path).path
        if rota == "/api/configurar":
            return self._configurar()
        if rota != "/api/clonar":
            return self._envia("não encontrado", "text/plain", 404)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            dados = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._envia('{"erro":"json"}', "application/json", 400)
        url = (dados.get("url") or "").strip()
        if not re.match(r"^https?://", url):
            return self._envia('{"erro":"url"}', "application/json", 400)
        tid = "%d" % (time.time() * 1000)
        with trava:
            tarefas[tid] = {"linhas": [], "acordar": threading.Event(),
                            "fim": False, "estado": "rodando",
                            "nome": "", "proc": None}
        threading.Thread(target=roda, daemon=True, args=(
            tid, url, (dados.get("link") or "").strip(),
            bool(dados.get("visivel")), (dados.get("proxy") or "").strip(),
            dados.get("conferir", True))).start()
        self._envia(json.dumps({"id": tid}), "application/json")


def main():
    porta = int(sys.argv[1]) if len(sys.argv) > 1 else PORTA
    s = ThreadingHTTPServer(("127.0.0.1", porta), Painel)
    print("echopage em http://localhost:%d/   (Ctrl+C para parar)" % porta, flush=True)
    try:
        s.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
