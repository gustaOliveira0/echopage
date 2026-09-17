/* ═══════════════════════════════════════════════════════════════
   CLONADOR DE PÁGINAS — passo 1 de 2: CAPTURA
   ───────────────────────────────────────────────────────────────
   1. Abra a página-alvo no Chrome (com VPN, se ela for geo-travada)
   2. Role a página até o fim (carrega imagens/vídeos preguiçosos)
   3. F12 → aba Console → cole isto → Enter
   4. Aguarde ">>> PRONTO <<<" e o download do .json
   ═══════════════════════════════════════════════════════════════ */
(async () => {
  const t0 = Date.now();
  const abs = u => { try { return new URL(u, location.href).href; } catch { return null; } };
  const urls = new Set();
  const log0 = [];
  // Caminho que o JavaScript ia montar e não montou: "${img}", "{{src}}",
  // "null", "__imgUrl_", "_cImageSrc_". Isso não é arquivo, é o molde cru
  // que sobrou no atributo. Buscar esses endereços traz a PÁGINA DE ERRO
  // do site com status 200, ela entra no clone como asset, e aí a limpeza
  // passa a enxergar as referências da página de erro — foi assim que 20
  // fontes de um Font Awesome que a página nem usa viraram "buraco".
  // O molde chega de três formas, e as três precisam ser decodificadas
  // antes de olhar: "${imgUrl}" vira "$%7BimgUrl%7D" na URL, a concatenação
  // que não fechou vira "+cImageSrc+", e o valor que faltou vira "null".
  const MOLDE = u => {
    let fim;
    try { fim = new URL(u).pathname.split('/').pop(); } catch (e) { return false; }
    if (!fim) return false;
    try { fim = decodeURIComponent(fim); } catch (e) {}
    if (/\$\{|\{\{|<%|#\{|\[object/i.test(fim)) return true;
    if (fim.includes('.')) return false;              // tem extensão: é arquivo
    return /^(null|undefined|nan|false|true)$/i.test(fim) ||
           /^[_+].*[_+]$/.test(fim);
  };
  const add = u => {
    const a = abs(u);
    if (a && /^https?:/.test(a) && !MOLDE(a)) urls.add(a);
  };

  // Domínios de tracking: baixá-los só gera erro de CORS e sujeira no clone.
  const SKIP = new RegExp([
    'googletagmanager', 'google-analytics', 'analytics\\.google', 'doubleclick',
    'clarity\\.ms', 'posthog', 'cloudflareinsights', 'convertexperiments',
    '/cdn-cgi/(rum|beacon|zaraz|challenge-platform|speculation)',
    'facebook\\.(net|com)', 'connect\\.facebook', 'hotjar', 'segment\\.(io|com)',
    'mixpanel', 'amplitude', 'intercom', 'tiktok\\.com', 'snapchat',
    'bat\\.bing\\.com', 'appspot\\.com', 'criteo', 'taboola', 'outbrain',
    'newrelic', 'sentry\\.io', 'datadoghq', 'optimizely', 'vwo\\.com',
    '/collect', '/g/collect', '/tr\\?', 'pixel', '_tracking',
    'heatmap\\.com', 'heatmapcore', 'klaviyo', '/pagead/'
  ].join('|'), 'i');

  // Mas a lista acima julga pelo NOME, e nome engana nos dois sentidos.
  // Barrar 'hero-pixel.png' ou uma imagem servida pelo redimensionador da
  // Cloudflare (/cdn-cgi/image/...) deixa buraco na página; já baixar à toa
  // um .gif de 1x1 de tracking não custa nada, porque o clonar.py tira
  // beacon pela FORMA, não pelo nome. Então mídia nunca é pulada: a lista
  // vale para script, iframe e beacon.
  const MIDIA = /\.(png|jpe?g|gif|webp|avif|svg|ico|bmp|mp4|webm|ogv|ogg|mov|m4v|mp3|m4a|wav|woff2?|ttf|otf|eot|css)(\?|#|$)/i;
  const pular = u => SKIP.test(u) && !MIDIA.test(u);

  // O buffer de resource-timing do Chrome guarda 250 entradas e descarta
  // calado tudo que passar disso. Numa landing com 400 arquivos, o que some
  // é justamente o fim da fila: as imagens e o vídeo que a rolagem carrega.
  // Aumentar o teto aqui já salva o que a rolagem logo abaixo vai buscar
  // (o buffer volta a aceitar assim que o limite sobe); o que carregou ANTES
  // de o script rodar só é recuperado pelo observador que o capturar.py
  // instala antes da página — daí a fusão das duas fontes na seção 1.
  try { performance.setResourceTimingBufferSize(20000); } catch (e) {}

  // O HTML que o SERVIDOR mandou, antes de qualquer JavaScript. O
  // outerHTML do fim da captura é a página DEPOIS do JS: o carrossel já
  // duplicou e reordenou os slides, o letreiro já se copiou, a animação
  // já terminou. No clone esse mesmo JS roda de novo por cima — e a
  // Guardality abria com a galeria fora de ordem e foto repetida. Com o
  // original, o JS do clone faz o que fez aqui: uma vez só. Busca de
  // dentro da página, com o cookie dela (passa pelo Cloudflare).
  // Passa pelo DOMParser: interpreta como o navegador interpreta, SEM rodar
  // script nenhum, e serializa do mesmo jeito que o outerHTML — aspas
  // duplas em todo atributo, que é a forma que a limpeza do clonar.py lê.
  const fonteP = fetch(location.href, { credentials: 'include' })
    .then(r => r.ok ? r.text() : '')
    .then(t => {
      if (!t || !/<(html|head|body)[\s>]/i.test(t)) return '';
      const doc = new DOMParser().parseFromString(t, 'text/html');
      return doc.documentElement ? doc.documentElement.outerHTML : '';
    })
    .catch(() => '');
  // atributo lido do HTML cru ainda está escapado: "a &amp; b.mp4"
  const desesc = v => (v || '').replace(/&amp;/g, '&').replace(/&#0?38;/g, '&');

  // ── 0. rola a página inteira para disparar lazy-load ─────────
  // muita imagem/vídeo só é baixado quando entra na tela; sem isto eles
  // nunca aparecem na captura.
  console.log('%c rolando a página para carregar tudo… ', 'background:#222;color:#0ff');
  await (async () => {
    const altura = () => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
    const passo = Math.max(300, innerHeight * 0.85);
    for (let y = 0; y < altura(); y += passo) {
      scrollTo(0, y);
      await new Promise(r => setTimeout(r, 180));
    }
    scrollTo(0, altura());
    await new Promise(r => setTimeout(r, 700));   // deixa o lazy-load do rodapé terminar
    scrollTo(0, 0);
    await new Promise(r => setTimeout(r, 250));
  })();

  // ── 1. tudo que o navegador já carregou ──────────────────────
  // Duas fontes que se somam: o buffer do navegador e a lista sem teto do
  // observador instalado pelo capturar.py antes de a página começar.
  performance.getEntriesByType('resource').forEach(e => add(e.name));
  (window.__CLONE_RES || []).forEach(add);
  if (!window.__CLONE_RES)
    console.warn('sem observador de recursos (captura colada à mão): o que ' +
                 'carregou antes deste script pode ter estourado o buffer de 250');

  // ── 2. varredura do DOM (pega <video> e atributos que o performance perde) ─
  document.querySelectorAll('*').forEach(el => {
    ['src', 'data-src', 'data-lazy-src', 'data-original', 'data-bg', 'data-background',
     'data-image', 'data-poster', 'poster', 'href', 'data'].forEach(at => add(el.getAttribute && el.getAttribute(at)));
    [el.getAttribute && el.getAttribute('srcset'), el.getAttribute && el.getAttribute('data-srcset')].forEach(ss =>
      (ss || '').split(',').forEach(s => add(s.trim().split(/\s+/)[0])));
  });
  document.querySelectorAll('video,audio').forEach(v => { add(v.src); add(v.currentSrc); add(v.poster); });
  document.querySelectorAll('[style*="url("]').forEach(el =>
    [...el.getAttribute('style').matchAll(/url\(['"]?([^'")]+)/g)].forEach(m => add(m[1])));

  // ── 2b. varredura por regex no HTML cru ──────────────────────
  // Pega o que querySelectorAll não enxerga: conteúdo de <noscript>
  // (é texto inerte quando o JS está ligado), <template>, e atributos
  // exóticos. Foi assim que um selo DMCA escapou de uma captura.
  {
    const cru = document.documentElement.outerHTML;
    for (const m of cru.matchAll(/(?:src|href|data-src|data-lazy-src)=["']([^"']+)["']/g)) add(desesc(m[1]));
    for (const m of cru.matchAll(/url\(\s*['"]?(?!data:)([^'")]+)/g)) add(desesc(m[1]));
  }
  const fonte = await fonteP;
  if (fonte) {
    for (const m of fonte.matchAll(/(?:src|href|data-src|data-lazy-src|data-srcset|srcset|poster)=["']([^"']+)["']/g))
      desesc(m[1]).split(',').forEach(x => add(x.trim().split(/\s+/)[0]));
    for (const m of fonte.matchAll(/url\(\s*['"]?(?!data:)([^'")]+)/g)) add(desesc(m[1]));
  }

  // ── 2bb. o que só o estilo calculado conhece ─────────────────
  // Fundo posto por JS depois do load, folha de terceiro que o fetch não
  // consegue ler, e sobretudo ::before/::after — que não são elementos e
  // por isso não aparecem em varredura de DOM nenhuma. Aqui a URL já vem
  // absoluta, resolvida pelo próprio navegador contra o CSS de origem.
  {
    const PROPS = ['background-image', 'border-image-source', 'mask-image',
                   '-webkit-mask-image', 'list-style-image', 'content', 'cursor'];
    const olhar = (el, pseudo) => {
      let cs;
      try { cs = getComputedStyle(el, pseudo); } catch (e) { return; }
      if (!cs) return;
      for (const p of PROPS) {
        const v = cs.getPropertyValue(p);
        if (!v || v === 'none' || v.indexOf('url(') < 0) continue;
        for (const m of v.matchAll(/url\(\s*['"]?(?!data:)([^'")]+)/g)) add(m[1]);
      }
    };
    const els = document.querySelectorAll('*');
    for (const el of els) { olhar(el, null); olhar(el, '::before'); olhar(el, '::after'); }
    console.log('estilo calculado: ' + els.length + ' elementos varridos (com ::before/::after)');
  }

  // ── 2c. IDIOMAS: descobre o seletor e busca cada versão traduzida ──
  // A tradução é feita no SERVIDOR (?lang=xx), então ela não vem junto no
  // download da página. Mas daqui de dentro dá: é fetch same-origin, leva o
  // cookie de clearance do Cloudflare e passa onde curl leva 403.
  const idiomas = {};
  {
    const norm = v => (v || '').trim().toLowerCase();
    const valido = c => /^[a-z]{2}(-[a-z0-9]{2,8})?$/.test(c);
    const atual = norm(document.documentElement.lang) ||
                  norm(new URL(location.href).searchParams.get('lang'));

    // Onde um seletor de idioma costuma estar. Só olhamos códigos que estão
    // DENTRO de algo assim — senão qualquer data-value da página viraria idioma.
    const DENTRO = '[class*="lang"],[class*="idioma"],[class*="locale"],' +
                   '[class*="switcher"],[id*="lang"],[id*="locale"]';

    const alvo = (el, c) => {
      const d = el.getAttribute('data-url') || el.getAttribute('data-href') ||
                el.getAttribute('href');
      if (d && !/^(#|javascript:)/i.test(d)) {
        const a = abs(d);
        if (a && new URL(a).origin === location.origin) return a;
      }
      const u = new URL(location.href);        // igual ao que o seletor faz
      u.searchParams.set('lang', c); u.hash = '';
      return u.href;
    };

    const cand = new Map(), rotulo = new Map();
    document.querySelectorAll(
      '[data-value],[data-lang],[data-language],[data-locale],[hreflang],option[value]'
    ).forEach(el => {
      const c = norm(el.getAttribute('data-value') || el.getAttribute('data-lang') ||
                     el.getAttribute('data-language') || el.getAttribute('data-locale') ||
                     el.getAttribute('hreflang') || el.value);
      if (!valido(c) || cand.has(c)) return;
      if (!el.hasAttribute('hreflang') && !el.closest(DENTRO)) return;
      cand.set(c, alvo(el, c));
      rotulo.set(c, (el.textContent || c).trim().slice(0, 40));
    });

    if (cand.size > 1) {
      console.log('%c seletor de idioma: ' + [...cand.keys()].join(', ') + ' ',
                  'background:#222;color:#ff0');
      const base = document.documentElement.outerHTML;
      for (const [c, u] of cand) {
        if (c === atual) { idiomas[c] = { url: location.href, atual: true }; continue; }
        try {
          const r = await fetch(u, { credentials: 'include' });
          if (!r.ok) { log0.push('HTTP' + r.status + ' idioma ' + c); continue; }
          const h = await r.text();
          if (!/<html/i.test(h)) { log0.push('sem html idioma ' + c); continue; }
          idiomas[c] = { url: u, html: h, rotulo: rotulo.get(c),
                         igual: h.length === base.length };
          // a versão traduzida pode trazer imagem/vídeo que a atual não tem
          for (const m of h.matchAll(/(?:src|href|data-src|poster)=["']([^"']+)["']/g)) add(m[1]);
          for (const m of h.matchAll(/url\(\s*['"]?(?!data:)([^'")]+)/g)) add(m[1]);
          console.log('  idioma ' + c + ': ' + (h.length / 1024).toFixed(0) + 'KB');
        } catch (e) { log0.push('ERR idioma ' + c); }
      }
    }
  }

  // ── 3. CSS: extrai backgrounds e @font-face de dentro ─────────
  // Guarda de qual CSS veio cada url() e como ela estava escrita: se a
  // busca der 404, dá para tentar as bases vizinhas (ver seção 4b).
  const deCss = new Map();
  const seenCss = new Set();
  for (let round = 0; round < 3; round++) {          // 3 níveis (@import)
    for (const cu of [...urls]) {
      if (seenCss.has(cu) || pular(cu)) continue;
      if (!/\.css($|\?)|fonts\.googleapis/.test(cu)) continue;
      seenCss.add(cu);
      try {
        const t = await (await fetch(cu)).text();
        [...t.matchAll(/url\(\s*['"]?(?!data:)([^'")]+)/g)].forEach(m => {
          try {
            const a = new URL(m[1], cu).href;
            if (MOLDE(a)) return;
            urls.add(a);
            if (!deCss.has(a)) deCss.set(a, { css: cu, bruto: m[1] });
          } catch {}
        });
        // url() acima já cobre "@import url(...)". Aqui só a forma sem url(),
        // e o padrão NÃO pode parar no ";" — a query do Google Fonts tem ";".
        [...t.matchAll(/@import\s+['"]([^'"]+)['"]/g)].forEach(m => {
          try { urls.add(new URL(m[1], cu).href); } catch {}
        });
      } catch { console.warn('css inacessível:', cu); }
    }
  }

  // ── 3b. as regras que o navegador já tem em memória ───────────
  // Cobre o que o passo acima não alcança: o <style> escrito no HTML, a
  // folha injetada por JS (que não tem URL para buscar) e aquela cujo
  // fetch falha. Se a folha é legível daqui, as regras estão todas aqui —
  // inclusive as de dentro de @media, que é onde mora a imagem que só o
  // celular usa e que o desktop nunca chegou a baixar.
  {
    let n = 0;
    const anda = (regras, base) => {
      for (const r of regras) {
        if (r.cssRules) { anda(r.cssRules, base); continue; }   // @media, @supports
        const t = r.cssText || '';
        if (t.indexOf('url(') < 0) continue;
        for (const m of t.matchAll(/url\(\s*['"]?(?!data:)([^'")]+)/g)) {
          try {
            const a = new URL(m[1], base).href;
            if (!/^https?:/.test(a) || MOLDE(a)) continue;
            if (!urls.has(a)) n++;
            urls.add(a);
            if (!deCss.has(a)) deCss.set(a, { css: base, bruto: m[1] });
          } catch (e) {}
        }
      }
    };
    for (const f of document.styleSheets) {
      let regras;
      try { regras = f.cssRules; } catch (e) { continue; }      // cross-origin: ilegível
      if (!regras) continue;
      try { anda(regras, f.href || location.href); } catch (e) {}
    }
    if (n) console.log('regras em memória: +' + n + ' arquivo(s) que o CSS baixado não citava');
  }

  // ── 4. baixa tudo em base64 ───────────────────────────────────
  const b64 = b => new Promise(r => {
    const f = new FileReader(); f.onloadend = () => r(f.result.split(',')[1]); f.readAsDataURL(b);
  });
  const list = [...urls].filter(u => !pular(u));
  const files = {}, log = log0;
  let i = 0, bytes = 0;
  console.log('%c capturando ' + list.length + ' arquivos… ', 'background:#222;color:#0f0');
  // ── 4b. resgate de url() de CSS que dá 404 ────────────────────
  // Caso clássico: o CSS foi movido de pasta e o "../../images/x.png"
  // ficou apontando um nível fora do lugar. O navegador engole calado e
  // o fundo some — foi assim que 12 imagens sumiram de um clone sem que
  // a auditoria acusasse nada. Aqui a gente tenta as bases vizinhas; de
  // dentro da página o fetch é same-origin e passa pelo Cloudflare.
  const resgatar = async u => {
    const info = deCss.get(u);
    if (!info || /^(https?:)?\/\//.test(info.bruto)) return null;
    const tentativas = new Set();
    let b = info.bruto.split('#')[0];
    const nu = b.replace(/^(\.\.\/)+/, '');          // sem nenhum ../
    for (let k = 0; k <= 4; k++) tentativas.add('../'.repeat(k) + nu);
    tentativas.add('/' + nu);
    // Duas bases, não uma: subir a partir do CSS cobre o caso de a folha
    // ter mudado de pasta; subir a partir da PÁGINA cobre o outro caso
    // comum, o de a pasta de imagens ser irmã da página e não do CSS.
    const cands = [];
    for (const base of [info.css, location.href])
      for (const t of tentativas) {
        let c;
        try { c = new URL(t, base).href; } catch { continue; }
        if (c !== u && cands.indexOf(c) < 0) cands.push(c);
      }
    for (const cand of cands) {
      if (files[cand]) continue;
      try {
        const r = await fetch(cand);
        if (!r.ok) continue;
        const bl = await r.blob();
        if (!bl.size) continue;
        return { blob: bl, de: cand };
      } catch {}
    }
    return null;
  };

  for (const u of list) {
    i++;
    try {
      // SEM credentials: com 'include' os CDNs quebram por CORS wildcard
      const r = await fetch(u);
      if (!r.ok) {
        const s = await resgatar(u);
        if (s) {
          // grava sob a URL ORIGINAL: é ela que o CSS cita, então a
          // reescrita do clonar.py acha sem precisar saber do resgate
          files[u] = { b64: await b64(s.blob), type: s.blob.type, size: s.blob.size };
          bytes += s.blob.size;
          log.push('RESGATE ' + u + ' <- ' + s.de);
          console.log('%c resgatada: ' + u.split('/').pop() + ' ', 'background:#222;color:#fa0');
          continue;
        }
        log.push('HTTP' + r.status + ' ' + u);
        continue;
      }
      const b = await r.blob();
      if (!b.size) { log.push('vazio ' + u); continue; }
      files[u] = { b64: await b64(b), type: b.type, size: b.size };
      bytes += b.size;
      if (i % 10 === 0) console.log(i + '/' + list.length + '  ' + (bytes / 1048576).toFixed(1) + 'MB');
    } catch (e) { log.push('ERR ' + u); }
  }

  // ── 5. segunda passada: o que só o JavaScript conhece ────────
  // Duas ausências clássicas, e as duas somem sem deixar rastro:
  //
  //   (a) O checkout destas páginas não está no HTML. Ele chega por AJAX,
  //       como um PEDAÇO de HTML servido de um .php — e traz os <img> do
  //       formulário (bandeira de cartão, cadeado, selo de desconto) e até
  //       o <link> do CSS dele. Nada disso o navegador carregou, porque
  //       ninguém abriu o formulário. Como o pedaço é HTML de verdade, as
  //       referências dele são referências de verdade: valem para qualquer
  //       extensão, não só mídia.
  //   (b) Slider e galeria guardam a lista de imagens num array de JS, e
  //       vídeo de modal só ganha src no clique. Aí o caminho é só um
  //       texto solto, e só cabe confiar quando ele TERMINA em extensão
  //       de mídia — senão qualquer string viraria candidata.
  //
  // O que não existir dá 404 e morre calado: nesta passada a ausência é o
  // esperado, não um buraco.
  {
    const EXT = /\.(png|jpe?g|gif|webp|avif|svg|bmp|mp4|webm|ogv|mov|m4v)(\?[^'"]*)?$/i;
    const TETO = 500;
    const extras = new Map();                 // url -> como foi achada
    const anota = (v, base, como) => {
      if (!v || /^data:/i.test(v)) return;
      let a;
      try { a = new URL(v.trim(), base).href; } catch (e) { return; }
      if (!/^https?:/.test(a)) return;
      try { if (new URL(a).origin !== new URL(base).origin) return; } catch (e) { return; }
      if (files[a] || urls.has(a) || extras.has(a) || pular(a) || MOLDE(a)) return;
      if (extras.size < TETO) extras.set(a, como);
    };

    const varrerMarcacao = (txt, base) => {
      for (const m of txt.matchAll(/<link\b[^>]*\bhref\s*=\s*["']([^"']+)["']/gi)) anota(m[1], base, 'fragmento');
      for (const m of txt.matchAll(/\b(?:src|data-src|data-lazy-src|data-original|poster)\s*=\s*["']([^"']+)["']/gi)) anota(m[1], base, 'fragmento');
      for (const m of txt.matchAll(/\bsrcset\s*=\s*["']([^"']+)["']/gi))
        m[1].split(',').forEach(x => anota(x.trim().split(/\s+/)[0], base, 'fragmento'));
      for (const m of txt.matchAll(/url\(\s*['"]?(?!data:)([^'")]+)/g)) anota(m[1], base, 'fragmento');
    };

    const texto = u => {
      const f = files[u];
      if (!f) return null;
      if (!/\.(js|json|html?|php|txt)($|\?)/i.test(u) &&
          !/(javascript|json|html|text\/plain)/i.test(f.type || '')) return null;
      let t;
      try { t = atob(f.b64); } catch (e) { return null; }
      return t.length > 4e6 ? t.slice(0, 4e6) : t;
    };

    // A página de erro do site vem com status 200 em muita hospedagem, então
    // ela chega aqui parecendo um fragmento legítimo. As referências dela
    // são do tema do erro, não da página — colher isso enche o clone de
    // arquivo que ninguém usa e de buraco que ninguém tem como tapar.
    const ehErro = t => {
      const m = /<title[^>]*>([^<]{0,120})/i.exec(t);
      return !!m && /\b(404|403|not found|forbidden|error|erro)\b/i.test(m[1]);
    };

    for (const u of Object.keys(files)) {
      const t = texto(u);
      if (t === null) continue;
      if (ehErro(t)) { log.push('PAGINA-DE-ERRO ' + u); continue; }
      if (/<(img|link|source|script|div|form|input)\b/i.test(t)) varrerMarcacao(t, u);
      for (const m of t.matchAll(/["'`]([^"'`\s<>()]{4,300})["'`]/g))
        if (EXT.test(m[1])) { anota(m[1], u, 'js'); anota(m[1], location.href, 'js'); }
    }

    // Duas ondas: um CSS que só apareceu agora ainda traz url() dentro.
    for (let onda = 0; onda < 2 && extras.size; onda++) {
      const lote = [...extras.keys()].filter(a => !files[a]);
      if (!lote.length) break;
      console.log('%c 2ª passada (onda ' + (onda + 1) + '): ' + lote.length +
                  ' caminho(s) que ninguém tinha carregado ', 'background:#222;color:#0ff');
      let achou = 0;
      for (const a of lote) {
        try {
          const r = await fetch(a);
          if (!r.ok) {
            // Referência de fragmento é referência de verdade: se ela dá
            // 404, quem não tem é a ORIGEM, e isso precisa ficar no log
            // para a conferência não cobrar do clone. Já o caminho achado
            // solto no meio do JS não vale registro: ali a ausência é o
            // normal, e logar encheria a auditoria de ruído.
            if (extras.get(a) === 'fragmento') {
              const s2 = await resgatar(a);
              if (s2) {
                files[a] = { b64: await b64(s2.blob), type: s2.blob.type,
                             size: s2.blob.size };
                bytes += s2.blob.size; achou++;
                log.push('RESGATE ' + a + ' <- ' + s2.de);
                continue;
              }
              log.push('HTTP' + r.status + ' ' + a);
            }
            continue;
          }
          const bl = await r.blob();
          if (!bl.size) continue;
          files[a] = { b64: await b64(bl), type: bl.type, size: bl.size };
          bytes += bl.size; achou++;
          log.push('EXTRA-' + extras.get(a).toUpperCase() + ' ' + a);
          if (/\.css($|\?)/i.test(a) || /css/i.test(bl.type || '')) {
            const t = await bl.text();
            for (const m of t.matchAll(/url\(\s*['"]?(?!data:)([^'")]+)/g)) {
              const alvo = anota(m[1], a, 'fragmento');
              try { const abs2 = new URL(m[1], a).href;
                    if (!deCss.has(abs2)) deCss.set(abs2, { css: a, bruto: m[1] }); } catch (e) {}
            }
          }
        } catch (e) {}
      }
      console.log('%c 2ª passada (onda ' + (onda + 1) + '): ' + achou +
                  ' existiam de verdade e entraram no clone ',
                  'background:#222;color:' + (achou ? '#0f0' : '#888'));
      if (!achou) break;
    }
  }

  const payload = JSON.stringify({
    pageUrl: location.href,
    title: document.title,
    capturedAt: new Date().toISOString(),
    viewport: { w: innerWidth, h: innerHeight },
    html: document.documentElement.outerHTML,
    fonte,
    // o outerHTML não traz o <!DOCTYPE>, e sem ele o clone abre em modo
    // quirks: outra altura de linha, outra caixa, outro layout
    doctype: document.doctype ? new XMLSerializer().serializeToString(document.doctype) : '',
    idiomas,
    files, log
  });

  console.log('%c ' + Object.keys(files).length + '/' + list.length + ' arquivos · ' +
    (bytes / 1048576).toFixed(1) + 'MB · ' + ((Date.now() - t0) / 1000).toFixed(0) + 's ',
    'background:#222;color:#0f0');
  if (log.length) console.warn('não capturados (' + log.length + '):', log);
  const nId = Object.keys(idiomas).filter(k => idiomas[k].html).length;
  if (nId) console.log('%c ' + nId + ' idioma(s) traduzidos capturados: ' +
    Object.keys(idiomas).join(', ') + ' ', 'background:#222;color:#ff0');

  const nome = 'captura-' + location.hostname.replace(/[^a-z0-9]+/gi, '-') + '.json';
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([payload], { type: 'application/json' }));
  a.download = nome;
  document.body.appendChild(a); a.click(); a.remove();
  console.log('%c >>> PRONTO — baixando ' + nome + ' <<< ', 'background:#0a0;color:#fff;font-size:14px');
  console.log('Se NADA baixar: procure o ícone de download bloqueado na barra de endereço ' +
              'e clique em "Permitir", ou recarregue a página (F5) e rode de novo.');
})();
