"""Cliente WebSocket/CDP mínimo — só stdlib, sem instalar nada.

O Chrome fala CDP por WebSocket. Em vez de trazer uma dependência para o
projeto (que até aqui roda com a biblioteca padrão), são ~90 linhas de
enquadramento RFC 6455. Só o necessário: texto, mascarado, com ping/pong.
"""
import base64, json, os, socket, ssl, struct, time
from urllib.parse import urlsplit
from urllib.request import urlopen


class WS:
    def __init__(self, url, timeout=180):
        sp = urlsplit(url)
        porta = sp.port or (443 if sp.scheme == "wss" else 80)
        self.s = socket.create_connection((sp.hostname, porta), timeout=timeout)
        if sp.scheme == "wss":
            self.s = ssl.create_default_context().wrap_socket(
                self.s, server_hostname=sp.hostname)
        chave = base64.b64encode(os.urandom(16)).decode()
        caminho = sp.path + ("?" + sp.query if sp.query else "")
        self.s.sendall((
            "GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\n"
            "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
            % (caminho, sp.hostname, porta, chave)).encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            p = self.s.recv(4096)
            if not p:
                raise IOError("handshake WebSocket falhou")
            buf += p
        if b"101" not in buf.split(b"\r\n")[0]:
            raise IOError("handshake recusado: %s" % buf.split(b"\r\n")[0])
        self.resto = buf.split(b"\r\n\r\n", 1)[1]

    def _ler(self, n):
        while len(self.resto) < n:
            p = self.s.recv(max(65536, n - len(self.resto)))
            if not p:
                raise IOError("conexão fechada")
            self.resto += p
        d, self.resto = self.resto[:n], self.resto[n:]
        return d

    def enviar(self, texto, opcode=1):
        d = texto.encode() if isinstance(texto, str) else texto
        n = len(d)
        cab = bytes([0x80 | opcode])
        if n < 126:
            cab += bytes([0x80 | n])
        elif n < 65536:
            cab += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            cab += bytes([0x80 | 127]) + struct.pack(">Q", n)
        m = os.urandom(4)
        self.s.sendall(cab + m + bytes(b ^ m[i % 4] for i, b in enumerate(d)))

    def receber(self):
        """Devolve o próximo quadro de texto, juntando continuações."""
        partes, op = [], None
        while True:
            b1, b2 = self._ler(2)
            fin, opcode = b1 & 0x80, b1 & 0x0F
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._ler(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._ler(8))[0]
            dados = self._ler(n) if n else b""
            if opcode == 0x8:
                raise IOError("servidor fechou a conexão")
            if opcode == 0x9:
                self.enviar(dados, opcode=0xA)     # pong
                continue
            if opcode == 0xA:
                continue
            if op is None:
                op = opcode
            partes.append(dados)
            if fin:
                return b"".join(partes).decode("utf-8", "replace")

    def fechar(self):
        try:
            self.enviar(b"", opcode=0x8)
            self.s.close()
        except Exception:
            pass


class Chrome:
    """Conversa com um Chrome que esteja com --remote-debugging-port."""

    def __init__(self, porta=9222, timeout=180):
        v = json.load(urlopen("http://127.0.0.1:%d/json/version" % porta, timeout=10))
        self.ws = WS(v["webSocketDebuggerUrl"], timeout=timeout)
        self.n = 0
        self.versao = v.get("Browser", "?")

    def cmd(self, metodo, params=None, sessao=None, espera=180):
        self.n += 1
        msg = {"id": self.n, "method": metodo, "params": params or {}}
        if sessao:
            msg["sessionId"] = sessao
        self.ws.enviar(json.dumps(msg))
        fim = time.time() + espera
        while time.time() < fim:
            r = json.loads(self.ws.receber())
            if r.get("id") == self.n:
                if "error" in r:
                    raise RuntimeError("%s: %s" % (metodo, r["error"].get("message")))
                return r.get("result", {})
        raise TimeoutError("sem resposta para %s" % metodo)

    def eventos_ate(self, nome, sessao=None, espera=60):
        fim = time.time() + espera
        while time.time() < fim:
            try:
                r = json.loads(self.ws.receber())
            except Exception:
                return False
            if r.get("method") == nome and (not sessao or r.get("sessionId") == sessao):
                return True
        return False

    def fechar(self):
        self.ws.fechar()
