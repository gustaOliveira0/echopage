#!/usr/bin/env python3
"""Encaminhador local para proxy COM usuário e senha.

O Chrome não aceita credenciais em `--proxy-server`: passar
`http://user:pass@host:porta` faz ele ignorar a senha e cair num diálogo
que ninguém responde numa automação. Este módulo sobe um proxy local sem
senha em 127.0.0.1, para onde o Chrome aponta, e ele repassa para o proxy
de verdade já com o `Proxy-Authorization` preenchido.

Assim o cliente não instala nada: o produto fornece o acesso geográfico e
o navegador só vê um proxy local.

Suporta CONNECT (https) e requisições http comuns.
"""
import base64
import select
import socket
import threading
from urllib.parse import urlsplit


class Encaminhador(threading.Thread):
    daemon = True

    def __init__(self, upstream, porta=0):
        """upstream: http://user:senha@host:porta (senha opcional)."""
        threading.Thread.__init__(self)
        sp = urlsplit(upstream if "://" in upstream else "http://" + upstream)
        if sp.scheme not in ("http", "https"):
            raise ValueError("só proxy http(s) — para socks use --proxy direto")
        self.alvo = (sp.hostname, sp.port or 8080)
        self.cab = b""
        if sp.username:
            cred = "%s:%s" % (sp.username, sp.password or "")
            self.cab = (b"Proxy-Authorization: Basic "
                        + base64.b64encode(cred.encode()) + b"\r\n")
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", porta))
        self.srv.listen(128)
        self.porta = self.srv.getsockname()[1]
        self.parar = False

    @property
    def endereco(self):
        return "http://127.0.0.1:%d" % self.porta

    def run(self):
        while not self.parar:
            try:
                cli, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self._atende, args=(cli,), daemon=True).start()

    def _atende(self, cli):
        cima = None
        try:
            cli.settimeout(60)
            dados = b""
            while b"\r\n\r\n" not in dados:
                p = cli.recv(65536)
                if not p:
                    return
                dados += p
                if len(dados) > 262144:
                    return
            # injeta a credencial no pedido que vai para o proxy de verdade
            cab, resto = dados.split(b"\r\n\r\n", 1)
            linhas = [l for l in cab.split(b"\r\n")
                      if not l.lower().startswith(b"proxy-authorization:")]
            novo = linhas[0] + b"\r\n" + self.cab + b"\r\n".join(linhas[1:]) \
                + b"\r\n\r\n" + resto

            cima = socket.create_connection(self.alvo, timeout=30)
            cima.sendall(novo)
            self._ponte(cli, cima)
        except Exception:
            pass
        finally:
            for s in (cli, cima):
                try:
                    s and s.close()
                except Exception:
                    pass

    @staticmethod
    def _ponte(a, b):
        a.setblocking(False)
        b.setblocking(False)
        while True:
            r, _, x = select.select([a, b], [], [a, b], 120)
            if x or not r:
                return
            for s in r:
                d = s.recv(65536)
                if not d:
                    return
                (b if s is a else a).sendall(d)

    def encerrar(self):
        self.parar = True
        try:
            self.srv.close()
        except Exception:
            pass


def prepara(proxy):
    """Devolve (endereco_para_o_chrome, encaminhador_ou_None).

    Proxy sem senha ou socks vai direto para o Chrome; com senha, sobe o
    encaminhador local.
    """
    if not proxy:
        return "", None
    sp = urlsplit(proxy if "://" in proxy else "http://" + proxy)
    if sp.scheme.startswith("socks") or not sp.username:
        return proxy, None
    enc = Encaminhador(proxy)
    enc.start()
    return enc.endereco, enc
