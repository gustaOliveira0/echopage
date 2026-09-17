/* ═══════════════════════════════════════════════════════════════
   SONDA DE CLIQUES — o que cada botão da página FAZ
   ───────────────────────────────────────────────────────────────
   Injetada pelo capturar.py depois da captura. Nome e classe não dizem
   o que um botão faz: o "Load More" das avaliações da Guardality tem a
   classe "cta" e só abre a lista; o joinha do comentário é um <button>
   solto que só troca o ícone. O filtro por nome mandava os dois para a
   oferta. Aqui a pergunta vai para a própria página: clica de verdade,
   com toda saída trancada, e olha o resultado.

     - tentou sair (navegar, abrir janela, enviar formulário) → "saida"
     - mudou a página sem sair dela                           → "ui"
     - não fez nada visível                                   → "nada"

   O clique em si é do capturar.py (Input.dispatchMouseEvent, um clique
   confiável, igual ao do visitante); aqui fica preparar e colher.
   ═══════════════════════════════════════════════════════════════ */
(() => {
  if (window.__sonda) return;

  // Classe de ESTADO muda com o clique e com o tempo; a assinatura do
  // elemento não pode depender dela, senão o botão clicado deixa de casar
  // com ele mesmo no clone.
  // inclusive o modificador BEM: glide__bullet--active, slick-active
  const ESTADO = /^(?:is-|has-)?(active|open|opened|show|shown|showing|selected|current|visible|hidden|in|collapsed|expanded|focus|focused|hover|hovered|pressed|disabled|loading|loaded|animated|aos-animate|lazyloaded|lazyload|checked)$|[-_](active|current|selected|open|opened|visible|hidden|expanded|collapsed|checked|disabled)$/i;
  // Região que muda sozinha: slider em autoplay, cronômetro, letreiro.
  // Mutação ali só conta se o clique foi dentro dela.
  const SOZINHA = /slider|carousel|swiper|glide|slick|splide|owl-|flickity|marquee|ticker|countdown|timer|clock|counter/i;
  const ALVO = 'a,button,input[type=submit],input[type=button],input[type=image],[onclick],[role=button]';

  const cls = el => {
    if (!el || el.className == null) return '';
    const c = el.className;
    return (c.baseVal !== undefined ? c.baseVal : c) + '';
  };
  const classes = el => cls(el).split(/\s+/).filter(x => x && !ESTADO.test(x)).sort();
  const texto = el => ((el.tagName === 'INPUT' ? el.value : el.textContent) ||
                       el.getAttribute('aria-label') || '')
    .replace(/\s+/g, ' ').trim().slice(0, 60);
  const paiCls = el => {
    let p = el.parentElement;
    for (let k = 0; p && k < 4; k++, p = p.parentElement) {
      const c = classes(p);
      if (c.length) return c;
    }
    return [];
  };
  const assinatura = el => ({ t: el.tagName.toLowerCase(), i: el.id || '',
                              c: classes(el), x: texto(el), p: paiCls(el) });
  const chave = a => [a.t, a.i, a.c.join('.'), a.x, a.p.join('.')].join('|');
  const visivel = el => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.display !== 'none' && +cs.opacity !== 0;
  };

  const candidatos = () => {
    const vistos = new Set(), lista = [];
    const poe = el => {
      if (!visivel(el)) return;
      const a = assinatura(el), k = chave(a);
      if (vistos.has(k)) return;              // o 2º joinha igual ao 1º não é sondado
      vistos.add(k);
      lista.push({ el, a, k });
    };
    document.querySelectorAll(ALVO).forEach(poe);
    // <div> com cara de botão: cursor de mãozinha, e o pai não tem
    for (const el of document.querySelectorAll('body *')) {
      if (el.closest(ALVO)) continue;
      let cs;
      try { cs = getComputedStyle(el); } catch (e) { continue; }
      if (cs.cursor !== 'pointer') continue;
      const p = el.parentElement;
      if (p && getComputedStyle(p).cursor === 'pointer') continue;
      poe(el);
    }
    return lista;
  };

  // ── saídas trancadas ──────────────────────────────────────────
  const reg = { nav: 0, abriu: 0, envio: 0 };
  try { window.open = function () { reg.abriu++; return null; }; } catch (e) {}
  try { window.alert = function () {}; window.confirm = function () { return true; };
        window.prompt = function () { return ''; }; } catch (e) {}
  try {
    navigation.addEventListener('navigate', e => {
      if (e.hashChange) return;              // #secao é rolagem, não saída
      reg.nav++;
      if (e.cancelable) e.preventDefault();
    });
  } catch (e) {}
  addEventListener('submit', e => { reg.envio++; e.preventDefault(); }, true);
  try {
    const sub = HTMLFormElement.prototype.submit;
    HTMLFormElement.prototype.submit = function () { reg.envio++; };
    HTMLFormElement.prototype.__submit = sub;
  } catch (e) {}
  // <a> que ninguém cancelou: é navegação, inclusive target=_blank (que o
  // evento navigate desta janela não vê). Registrado por último, na janela,
  // roda depois dos handlers da página.
  addEventListener('click', e => {
    const a = e.target && e.target.closest && e.target.closest('a[href]');
    if (!a || e.defaultPrevented) return;
    const h = (a.getAttribute('href') || '').trim();
    if (!h || h.charAt(0) === '#' || /^javascript:/i.test(h)) return;
    reg.nav++;
    e.preventDefault();
  });

  // ── o que muda sozinho não é efeito do clique ────────────────
  // Dois descontos, e nenhum pode ser para sempre. Um carrossel em
  // autoplay mexe nos MESMOS nós que a seta dele mexe: marcar esses nós
  // como ruído de uma vez por todas fazia a seta dos depoimentos da
  // Guardality parecer sem efeito. Por isso:
  //   - fixo: o que muda de novo e de novo na observação inicial
  //     (cronômetro de 1 s, letreiro, slider rápido);
  //   - agora: o que mudou nos 450 ms antes deste clique, só para ele.
  const observar = ms => new Promise(res => {
    const recs = [];
    const mo = new MutationObserver(r => {
      const t = performance.now();
      for (const x of r) recs.push({ r: x, t });
    });
    mo.observe(document.documentElement, { subtree: true, childList: true,
      attributes: true, characterData: true, attributeOldValue: true });
    setTimeout(() => {
      const t = performance.now();
      for (const x of mo.takeRecords()) recs.push({ r: x, t });
      mo.disconnect();
      res(recs);
    }, ms);
  });
  const fixo = new WeakSet(), agitada = new WeakSet();
  let agora = new WeakSet();
  const regioes = n => {
    const out = [];
    for (let p = n.nodeType === 1 ? n : n.parentElement; p && p !== document.body; p = p.parentElement)
      if (SOZINHA.test(cls(p))) out.push(p);
    return out;
  };
  // "de novo e de novo" = mudou em dois momentos a mais de 400 ms um do outro
  const anotaFixo = recs => {
    const vez = new Map(), vezReg = new Map();
    const marca = (mapa, alvo, t, conj) => {
      const t0 = mapa.get(alvo);
      if (t0 === undefined) mapa.set(alvo, t);
      else if (t - t0 > 400) conj.add(alvo);
    };
    for (const { r, t } of recs) {
      marca(vez, r.target, t, fixo);
      if (r.target.parentNode) marca(vez, r.target.parentNode, t, fixo);
      for (const p of regioes(r.target)) marca(vezReg, p, t, agitada);
    }
  };
  const anotaAgora = recs => {
    agora = new WeakSet();
    for (const { r } of recs) {
      agora.add(r.target);
      if (r.target.parentNode) agora.add(r.target.parentNode);
    }
  };
  const ruido = n => fixo.has(n) || agora.has(n);

  const INERTE = /^(SCRIPT|IFRAME|NOSCRIPT|LINK|STYLE|META)$/;
  const relevante = (r, el) => {
    const n = r.target;
    if (ruido(n) || (n.parentNode && ruido(n.parentNode))) return false;
    if (r.type === 'childList') {
      const nos = [...r.addedNodes, ...r.removedNodes].filter(x =>
        x.nodeType === 1 || (x.nodeType === 3 && x.textContent.trim()));
      if (!nos.length) return false;
      // o que rastreador pendura no clique: script, iframe, pixel 1x1
      if (nos.every(x => x.nodeType === 1 && (INERTE.test(x.tagName) ||
          (x.tagName === 'IMG' && x.width <= 2 && x.height <= 2)))) return false;
    } else if (r.type === 'attributes') {
      const nome = r.attributeName || '';
      const agora = n.getAttribute ? n.getAttribute(nome) : null;
      if (r.oldValue === agora) return false;
      if (/^data-(focus|hover|hj-|clarity|gtm|vwo)/i.test(nome)) return false;
      if (nome === 'class') {
        const a = new Set((r.oldValue || '').split(/\s+/).filter(Boolean));
        const b = new Set((agora || '').split(/\s+/).filter(Boolean));
        const dif = [...a, ...b].filter(x => !(a.has(x) && b.has(x)));
        if (!dif.length || dif.every(x => /focus|hover|ripple|waves|pressed|touch/i.test(x)))
          return false;
      }
    }
    for (const p of regioes(n))
      if (agitada.has(p) && !p.contains(el)) return false;
    return true;
  };

  let lista = [], atual = null;

  window.__sonda = {
    listar() {
      lista = candidatos();
      return lista.map(c => ({ k: c.k, a: c.a }));
    },
    async ruidoGlobal(ms) {
      anotaFixo(await observar(ms));
      return true;
    },
    // Rola até o elemento, deixa assentar o que a rolagem dispara (lazy-load,
    // animação de entrada) e liga a observação. Devolve o ponto do clique —
    // ou clicavel:false se outra coisa está por cima dele ali.
    async preparar(k) {
      let c = lista.find(x => x.k === k);
      if (!c || !c.el.isConnected) {
        lista = candidatos();
        c = lista.find(x => x.k === k);
      }
      if (!c || !visivel(c.el)) return { ok: false };
      c.el.scrollIntoView({ block: 'center', inline: 'center' });
      anotaAgora(await observar(450));
      const r = c.el.getBoundingClientRect();
      const x = r.left + r.width / 2, y = r.top + r.height / 2;
      const topo = document.elementFromPoint(x, y);
      atual = {
        el: c.el, reg: { ...reg },
        nres: performance.getEntriesByType('resource').length,
        obs: observar(900),
      };
      return { ok: true, x, y, clicavel: !!topo && (topo === c.el || c.el.contains(topo)) };
    },
    clicarJs() { try { atual.el.click(); } catch (e) {} return true; },
    async colher() {
      if (!atual) return null;
      const recs = await atual.obs;
      const el = atual.el;
      const rel = recs.filter(({ r }) => relevante(r, el));
      const saiu = reg.nav > atual.reg.nav || reg.abriu > atual.reg.abriu ||
                   reg.envio > atual.reg.envio;
      const novos = performance.getEntriesByType('resource').slice(atual.nres)
        .map(e => e.name);
      atual = null;
      // Tudo o que mudou foi num carrossel que não contém o botão? Pode ser
      // o autoplay dele coincidindo com o clique — o capturar.py clica de
      // novo para confirmar antes de chamar isso de interface.
      const fora = rel.length > 0 && rel.every(({ r }) =>
        regioes(r.target).some(p => !p.contains(el)));
      return { v: saiu ? 'saida' : (rel.length ? 'ui' : 'nada'), mud: rel.length,
               fora, novos };
    },
    async baixar(urls) {
      const b64 = b => new Promise(r => {
        const f = new FileReader();
        f.onloadend = () => r(String(f.result).split(',')[1] || '');
        f.readAsDataURL(b);
      });
      const out = {};
      for (const u of urls) {
        try {
          const r = await fetch(u);
          if (!r.ok) { out[u] = { erro: 'HTTP' + r.status }; continue; }
          const b = await r.blob();
          if (!b.size) continue;
          out[u] = { b64: await b64(b), type: b.type, size: b.size };
        } catch (e) { out[u] = { erro: 'ERR' }; }
      }
      return out;
    },
  };
})();
