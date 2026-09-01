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
  const add = u => { const a = abs(u); if (a && /^https?:/.test(a)) urls.add(a); };

  // Domínios de tracking: baixá-los só gera erro de CORS e sujeira no clone.
  const SKIP = new RegExp([
    'googletagmanager', 'google-analytics', 'analytics\\.google', 'doubleclick',
    'clarity\\.ms', 'posthog', 'cloudflareinsights', 'cdn-cgi', 'convertexperiments',
    'facebook\\.(net|com)', 'connect\\.facebook', 'hotjar', 'segment\\.(io|com)',
    'mixpanel', 'amplitude', 'intercom', 'tiktok\\.com', 'snapchat',
    'bat\\.bing\\.com', 'appspot\\.com', 'criteo', 'taboola', 'outbrain',
    'newrelic', 'sentry\\.io', 'datadoghq', 'optimizely', 'vwo\\.com',
    '/collect', '/g/collect', '/tr\\?', 'pixel', '_tracking'
  ].join('|'), 'i');

  // ── 1. tudo que o navegador já carregou ──────────────────────
  performance.getEntriesByType('resource').forEach(e => add(e.name));

  // ── 2. varredura do DOM (pega <video> que o performance perde) ─
  document.querySelectorAll('img,script,video,audio,source,track,embed,object,link[href]').forEach(el => {
    add(el.getAttribute('src') || el.getAttribute('data-src') ||
        el.getAttribute('data-lazy-src') || el.getAttribute('href') || el.getAttribute('data'));
    [el.getAttribute('srcset'), el.getAttribute('data-srcset')].forEach(ss =>
      (ss || '').split(',').forEach(s => add(s.trim().split(/\s+/)[0])));
  });
  document.querySelectorAll('video,audio').forEach(v => { add(v.src); add(v.currentSrc); });
  document.querySelectorAll('[style*="url("]').forEach(el =>
    [...el.getAttribute('style').matchAll(/url\(['"]?([^'")]+)/g)].forEach(m => add(m[1])));

  // ── 2b. varredura por regex no HTML cru ──────────────────────
  // Pega o que querySelectorAll não enxerga: conteúdo de <noscript>
  // (é texto inerte quando o JS está ligado), <template>, e atributos
  // exóticos. Foi assim que um selo DMCA escapou de uma captura.
  {
    const cru = document.documentElement.outerHTML;
    for (const m of cru.matchAll(/(?:src|href|data-src|data-lazy-src)=["']([^"']+)["']/g)) add(m[1]);
    for (const m of cru.matchAll(/url\(\s*['"]?(?!data:)([^'")]+)/g)) add(m[1]);
  }

  // ── 3. CSS: extrai backgrounds e @font-face de dentro ─────────
  const seenCss = new Set();
  for (let round = 0; round < 2; round++) {          // 2 níveis (@import)
    for (const cu of [...urls]) {
      if (seenCss.has(cu) || SKIP.test(cu)) continue;
      if (!/\.css($|\?)|fonts\.googleapis/.test(cu)) continue;
      seenCss.add(cu);
      try {
        const t = await (await fetch(cu)).text();
        [...t.matchAll(/url\(\s*['"]?(?!data:)([^'")]+)/g)].forEach(m => {
          try { urls.add(new URL(m[1], cu).href); } catch {}
        });
        // url() acima já cobre "@import url(...)". Aqui só a forma sem url(),
        // e o padrão NÃO pode parar no ";" — a query do Google Fonts tem ";".
        [...t.matchAll(/@import\s+['"]([^'"]+)['"]/g)].forEach(m => {
          try { urls.add(new URL(m[1], cu).href); } catch {}
        });
      } catch { console.warn('css inacessível:', cu); }
    }
  }

  // ── 4. baixa tudo em base64 ───────────────────────────────────
  const b64 = b => new Promise(r => {
    const f = new FileReader(); f.onloadend = () => r(f.result.split(',')[1]); f.readAsDataURL(b);
  });
  const list = [...urls].filter(u => !SKIP.test(u));
  const files = {}, log = [];
  let i = 0, bytes = 0;
  console.log('%c capturando ' + list.length + ' arquivos… ', 'background:#222;color:#0f0');
  for (const u of list) {
    i++;
    try {
      // SEM credentials: com 'include' os CDNs quebram por CORS wildcard
      const r = await fetch(u);
      if (!r.ok) { log.push('HTTP' + r.status + ' ' + u); continue; }
      const b = await r.blob();
      if (!b.size) { log.push('vazio ' + u); continue; }
      files[u] = { b64: await b64(b), type: b.type, size: b.size };
      bytes += b.size;
      if (i % 10 === 0) console.log(i + '/' + list.length + '  ' + (bytes / 1048576).toFixed(1) + 'MB');
    } catch (e) { log.push('ERR ' + u); }
  }

  const payload = JSON.stringify({
    pageUrl: location.href,
    title: document.title,
    capturedAt: new Date().toISOString(),
    viewport: { w: innerWidth, h: innerHeight },
    html: document.documentElement.outerHTML,
    files, log
  });

  console.log('%c ' + Object.keys(files).length + '/' + list.length + ' arquivos · ' +
    (bytes / 1048576).toFixed(1) + 'MB · ' + ((Date.now() - t0) / 1000).toFixed(0) + 's ',
    'background:#222;color:#0f0');
  if (log.length) console.warn('não capturados (' + log.length + '):', log);

  const nome = 'captura-' + location.hostname.replace(/[^a-z0-9]+/gi, '-') + '.json';
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([payload], { type: 'application/json' }));
  a.download = nome;
  document.body.appendChild(a); a.click(); a.remove();
  console.log('%c >>> PRONTO — baixando ' + nome + ' <<< ', 'background:#0a0;color:#fff;font-size:14px');
  console.log('Se NADA baixar: procure o ícone de download bloqueado na barra de endereço ' +
              'e clique em "Permitir", ou recarregue a página (F5) e rode de novo.');
})();
