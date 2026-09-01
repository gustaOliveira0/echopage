# Clonador de Páginas

Clona uma página web inteira para rodar em `localhost` — incluindo vídeos,
backgrounds de CSS e fontes — mesmo quando o site é **geo-restrito** ou está
atrás de **Cloudflare** e não responde a `wget`/`curl`.

A captura roda **dentro do seu navegador**, então herda a sua sessão, seus
cookies e sua VPN. É por isso que funciona onde ferramentas de linha de
comando batem em 403.

---

## Caminho das pedras

### 1. Abrir a página no Chrome

Com VPN ligada, se o site exigir. Deixe a aba carregar por completo.

> **Role a página até o fim antes de capturar.** Imagens e vídeos com
> carregamento preguiçoso (*lazy load*) só entram na captura depois que
> aparecem na tela.

### 2. Rodar o capturador no console

`F12` → aba **Console** → cole o conteúdo de [`capturar.js`](capturar.js) → Enter.

Para pegar o script sem abrir editor:

```bash
./copiar.sh     # copia pro clipboard, ou abre no navegador se não houver ferramenta
```

Acompanhe o progresso. No fim aparece:

```
>>> PRONTO — baixando captura-exemplo-com.json <<<
```

O arquivo cai em `~/Downloads/`.

### 3. Reconstruir

```bash
./clonar.py ~/Downloads/captura-exemplo-com.json
```

Ou dando um nome à pasta:

```bash
./clonar.py ~/Downloads/captura-exemplo-com.json meu-clone
```

Ele grava os assets, reescreve HTML e CSS para caminhos locais, neutraliza
os rastreadores e imprime uma auditoria no fim:

```
=== AUDITORIA ===
refs locais: 69 | faltando: 0
domínios externos em código ativo: nenhum
tamanho: 41.8 MB em 86 arquivos
```

**`faltando: 0` e `chamadas externas automáticas: nenhuma` é o que você quer
ver.** Se aparecer algo, veja [Quando falta arquivo](#quando-falta-arquivo).

Antes de auditar, o script tenta baixar **do terminal** o que a captura no
navegador não conseguiu (CDN público bloqueado por CORS) e localiza as fontes
do Google Fonts referenciadas dentro dos CSS — é o que deixa o clone rodando
sem internet. Para pular essa etapa: `--offline`.

### 4. Servir

```bash
./servir.py meu-clone          # abre em http://localhost:8080
./servir.py meu-clone 9000     # em outra porta
./servir.py                    # lista os clones que existem
```

---

## Armadilhas (todas já resolvidas nos scripts)

Cada uma dessas custou uma tentativa perdida. Estão documentadas para você
não refazer o caminho errado.

| Armadilha | O que acontece | Solução aplicada |
|---|---|---|
| **`Ctrl+S` do Chrome** | Salva HTML e imagens, mas **ignora `<video>`** e os `url()` de dentro dos CSS | `capturar.js` varre o DOM e lê o conteúdo dos CSS |
| **`credentials: 'include'`** | Quebra por CORS em CDN público: *"Access-Control-Allow-Origin must not be the wildcard `*` when credentials mode is include"* — derruba jQuery, Swiper, Splide | `fetch()` sem credentials |
| **Downloads múltiplos** | O Chrome bloqueia o 2º download em diante sem gesto do usuário. Baixa 1 arquivo e os outros 11 somem **sem erro nenhum** | Tudo vai em **um único** `.json` |
| **POST para `127.0.0.1`** | Bloqueado: *"Permission was denied for this request to access the `loopback` address space"* (Private Network Access) | Não usamos; ficou o download |
| **`curl`/`wget` diretos** | 403 da Cloudflare — inclusive nos arquivos estáticos, não só no HTML | Captura roda no navegador |
| **MIME de `.webp`/`.webm`** | `python -m http.server` entrega como `application/octet-stream` | `servir.py` registra os tipos certos |
| **Extensões injetam lixo** | VPNs e afins metem `<script src="chrome-extension://…">` no HTML salvo | Neutralizados na reconstrução |
| **Fontes ficam remotas** | O `@import` do Google Fonts vive dentro do CSS, fora do alcance da varredura do HTML | `clonar.py` varre os CSS e baixa as fontes |
| **Substituição aninhada** | Trocar a URL pelo caminho local faz a variante curta (`/x.js`) casar dentro do resultado (`assets/x.js`) e virar `assetsassets/x.js` | Substituição em duas fases, via token |

---

## Quando falta arquivo

A auditoria lista o que não foi encontrado. Causas, em ordem de frequência:

1. **Não rolou a página até o fim** → recarregue, role, capture de novo.
2. **Conteúdo atrás de interação** (aba, acordeão, modal, carrossel) → abra
   manualmente antes de capturar.
3. **Download bloqueado** → procure o ícone de download bloqueado na barra de
   endereço e clique em *Permitir*; ou `F5` e rode de novo.
4. **Asset de outro domínio sem CORS** → aparece em `não capturados` no
   console. Baixe à mão e jogue em `clones/<nome>/assets/`.

---

## O que o clone preserva e o que ele corta

**Preserva:** HTML já renderizado, CSS, JS do próprio site, imagens, vídeos,
fontes, bibliotecas (jQuery, Swiper, Splide…).

**Corta:** Google Tag Manager, GA4, Meta Pixel, TikTok, PostHog, Microsoft
Clarity, Hotjar, Segment, Mixpanel, Amplitude, Sentry, redes de afiliados,
beacons da Cloudflare e scripts injetados por extensões.

Nada é apagado — os scripts viram `type="text/plain"` com o atributo
`data-clone-disabled="motivo"`. Para inspecionar o que foi cortado:

```bash
grep -o 'data-clone-disabled="[^"]*"' clones/<nome>/index.html | sort | uniq -c
```

Para reconstruir mantendo tudo ligado (**cuidado:** dispara analytics de
verdade, com dados falsos, na conta de quem você clonou):

```bash
./clonar.py captura.json --manter-trackers
```

### Analytics em domínio próprio

Muitos sites servem o rastreador pelo **próprio domínio** (proxy reverso) para
driblar adblock — por exemplo `p.exemplo.com/static/array.js`, que é PostHog
disfarçado. A lista genérica não tem como adivinhar esses domínios, então a
auditoria avisa:

```
!! 1 domínio(s) que a página ainda chama SOZINHA ao abrir:
     - p.exemplo.com
   Se for analytics em domínio próprio, rode de novo com:
     --bloquear p.exemplo.com
```

Confira se o domínio é rastreador mesmo (pode ser o CDN legítimo do site) e,
se for, refaça com `--bloquear`.

---

## Limites

- Página **estática**. Formulários, checkout e qualquer coisa que dependa do
  backend não funcionam — os links continuam apontando para o site original.
- Captura **um** estado da página: um viewport, um idioma, uma variação de
  teste A/B. Para a versão mobile, ative o modo dispositivo no DevTools,
  recarregue e capture de novo.
- Conteúdo carregado depois (scroll infinito, "carregar mais") só entra se
  você provocar antes de capturar.

---

## Uso responsável

Serve para estudo de layout, referência de implementação e arquivo pessoal.
O conteúdo continua sendo de quem o produziu — republicar um clone como se
fosse seu é violação de direitos autorais, e reproduzir a página de uma marca
num domínio que você controla é a mecânica de um golpe de phishing. Mantenha
em `localhost`.
