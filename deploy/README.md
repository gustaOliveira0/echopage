# Colocar o echopage numa VPS

Backend (Chrome + captura) na VPS, frontend na Vercel.

## Antes de começar: leia isto

**IP de datacenter é tratado pior pelo Cloudflare.** Parte do motivo de o
echopage funcionar na sua máquina é o IP residencial. Numa VPS, sites que hoje
abrem podem passar a responder `Sorry, you have been blocked`. O clonador
detecta e avisa, mas a solução é a mesma de sempre: `--proxy` com IP
residencial, configurado no painel.

Vale medir antes de investir: rode uma captura de teste na VPS com dois ou três
sites que te interessam.

**A API não pode ficar aberta.** Quem alcançar a porta manda o seu servidor
baixar qualquer site da internet. O `instalar.sh` gera um token obrigatório —
não desative.

## 1. Na VPS

```bash
ssh usuario@sua-vps
sudo apt install -y git
git clone https://github.com/gustaOliveira0/echopage.git /tmp/echopage
sudo bash /tmp/echopage/deploy/instalar.sh
```

Instala Python, Chrome, Xvfb e as bibliotecas gráficas que o Chrome exige;
clona o projeto em `/opt/echopage`; cria o usuário `echopage`; gera o token em
`/etc/echopage.env`; e sobe o serviço.

**Anote o token que ele imprime no final.**

## 2. Domínio e HTTPS

A página na Vercel é HTTPS, e o navegador **bloqueia** chamada de HTTPS para
HTTP puro. Sem domínio com certificado, a operação não funciona — não é
detalhe, é impeditivo.

Aponte um subdomínio para o IP da VPS (registro `A`), depois:

```bash
sudo cp /opt/echopage/deploy/nginx-echopage.conf /etc/nginx/sites-available/echopage
sudo nano /etc/nginx/sites-available/echopage        # troque api.seudominio.com
sudo ln -s /etc/nginx/sites-available/echopage /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d api.seudominio.com
```

Confira: `curl https://api.seudominio.com/saude` → `{"ok":true}`

## 3. Frontend na Vercel

```bash
cd web
npx vercel --prod
```

São arquivos estáticos: sem build, sem dependência.

Depois, no `/etc/echopage.env` da VPS, ponha o domínio que a Vercel deu:

```
ECHOPAGE_ORIGENS=https://echopage-xxx.vercel.app
```

```bash
sudo systemctl restart echopage
```

Sem isso o navegador barra as chamadas por CORS.

## 4. Conectar

Abra a página da Vercel. Na primeira vez ela pede o endereço da API e o token;
ficam guardados no navegador. O link "trocar" no rodapé limpa.

## Operação

```bash
systemctl status echopage          # está de pé?
journalctl -u echopage -f          # log ao vivo
systemctl restart echopage         # depois de mexer no .env
cd /opt/echopage && sudo -u echopage git pull && sudo systemctl restart echopage
```

Os clones ficam em `/opt/echopage/clones/` e **crescem rápido** — 30 a 100 MB
cada. Vale uma limpeza periódica:

```bash
find /opt/echopage/clones -maxdepth 1 -mtime +7 -type d -exec rm -rf {} +
```

## Se der errado

| sintoma | causa provável |
|---|---|
| `502` no nginx | serviço parado — `journalctl -u echopage -n 50` |
| CORS no console | falta o domínio da Vercel em `ECHOPAGE_ORIGENS` |
| `401` | token errado; confira `/etc/echopage.env` |
| log ao vivo trava | `proxy_buffering off` faltando no nginx |
| `Sorry, you have been blocked` | IP de datacenter — use `--proxy` |
| Chrome não abre | faltou biblioteca: `google-chrome --version` na VPS |
