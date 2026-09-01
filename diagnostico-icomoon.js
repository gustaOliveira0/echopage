/* Cole no Console da PÁGINA ORIGINAL (com VPN).
   Descobre onde está a fonte de ícones e baixa se achar. */
(async () => {
  console.log('icomoon carregou nesta página?', document.fonts.check('16px icomoon'));
  const carregadas = [...document.fonts].map(f => f.family + ' [' + f.status + ']');
  console.log('fontes registradas:', carregadas);

  const base = location.origin + '/offer/2/app/desktop/fonts/index/';
  const variantes = [];
  for (const ext of ['woff2', 'woff', 'ttf']) {
    variantes.push(
      base + 'icomoon-f%EF%B9%964eenn0.' + ext,   // como está no CSS
      base + 'icomoon-f?4eenn0.' + ext,           // com ? de verdade
      base + 'icomoon-f4eenn0.' + ext,            // sem o caractere
      base + 'icomoon-f.' + ext,
      base + 'icomoon.' + ext
    );
  }
  const achados = {};
  for (const u of variantes) {
    try {
      const r = await fetch(u, { method: 'GET' });
      if (r.ok) {
        const b = await r.blob();
        if (b.size > 500) { achados[u] = b.size; console.log('ACHOU', b.size, u); }
      }
    } catch {}
  }
  if (!Object.keys(achados).length) {
    console.warn('nenhuma variante existe no servidor — os ícones estão quebrados na ORIGEM também.');
    return;
  }
  // baixa a maior (mais completa)
  const melhor = Object.entries(achados).sort((a, b) => b[1] - a[1])[0][0];
  const b = await (await fetch(melhor)).blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(b);
  a.download = 'icomoon.' + melhor.split('.').pop();
  document.body.appendChild(a); a.click(); a.remove();
  console.log('>>> baixando', a.download, '<<<');
})();
