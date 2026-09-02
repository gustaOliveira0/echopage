# Projeto: Clonador de Páginas

Clonar uma landing page e servi-la em `localhost` preservando todo o visual e a
interatividade, removendo apenas o rastreamento, e (quando pedido) apontando os
links `<a>` para uma URL fornecida.

## Escopo exato — faça isto, nada além

1. **Manter todas as características visuais e de frontend.**
   Layout, CSS, imagens, vídeos, fontes e todo o JavaScript de interface:
   FAQ accordion, cronômetro/countdown, sliders/carrosséis, animações, menu,
   máscaras, validação de formulário, datas dinâmicas. A página deve ficar
   visualmente idêntica e funcional.

2. **Remover do JavaScript apenas o que NÃO é frontend** — ou seja, o
   rastreamento e analytics: Google Tag Manager, GA4, Meta/Facebook Pixel,
   TikTok, Microsoft Clarity, Hotjar, Segment, Mixpanel, Amplitude, Sentry,
   PostHog, e os pixels/beacons invisíveis.
   Regra de decisão: um script que **só manipula a interface FICA**; um script
   que **envia dados de navegação para terceiros SAI**. Na dúvida real,
   **mantenha** — o lado seguro é preservar o frontend, porque remover um
   script de UI quebra a página.
   Atenção: o `src` do tracker pode ter sido reescrito para `assets/xxx.js`,
   escondendo o domínio; a decisão olha a **URL de origem**, não o nome local.

3. **Todo clone sai com seletor de idioma próprio.** A página pode ter um ou
   não — o clonador injeta o dele: um botão flutuante isolado em Shadow DOM,
   responsivo, que não depende do CSS nem do JS do site. A troca é na hora,
   trocando o texto pelo dicionário: sem recarregar, sem query string, sem
   servidor, sem chamada externa. O idioma em que a página abre é o do
   `--idioma`; a escolha do visitante fica no `localStorage`.

   As traduções vêm de duas fontes, nesta ordem:

   a. **Do próprio site.** Muitas dessas páginas traduzem no servidor
      (`?lang=en`), então a tradução não vem no HTML baixado. O `capturar.js`
      detecta o seletor nativo, descobre os códigos e busca cada versão por
      `fetch` same-origin — de dentro da página ele leva o cookie do
      Cloudflare e passa onde `curl` leva 403. O `clonar.py` casa a original
      com a traduzida (mesmo template, mesma ordem de texto) e vira dicionário.
   b. **De `i18n/<código>.json`**, escrito à mão na pasta do clone. Chave =
      texto original, valor = tradução. Para o que falta, o `clonar.py` grava
      `i18n/_base.json` com todos os termos da página, prontos para preencher.

   Idioma sem dicionário não entra na lista. Se a página tem seletor nativo,
   as opções dele são religadas ao mesmo mecanismo, e as sem dicionário ficam
   inertes — nunca caem no `--link`.

4. **Mandar toda navegação para a URL fornecida** (`--link`). Qualquer coisa
   que levaria o visitante a **outra página** — link externo, `<a>` para outra
   página, botão de troca de página (`<button onclick="nextPage()">` e afins),
   submit de formulário — passa a apontar para a URL dada; o `href` visível
   (hover) também. O que **permanece na página** não é tocado: âncoras internas
   (`#`) e interações de UI (FAQ, slider, menu, cronômetro).

## Ferramentas (em `~/clonador-paginas`)

- **`capturar.js`** — cole no Console (F12) da página já aberta no navegador;
  baixa um `.json` com o HTML e todos os assets. Roda no navegador para herdar
  a sessão e a VPN quando a página é geo-restrita.
- **`clonar.py <captura.json> <nome> [--link "<url>"]`** — reconstrói em
  `clones/<nome>/`, remove o rastreamento, gera as páginas de idioma e, com
  `--link`, aponta os `<a>` para a URL. Imprime uma auditoria — o esperado é
  `faltando: 0` e `chamadas externas automáticas: nenhuma`.

  A decisão sobre o que é tracking tem **três níveis**, nesta ordem:
  `TRACKER_DOMINIOS` (sai sempre: GTM, GA, Meta, Clarity, Hotjar, e redes de
  afiliado como maxweb/Everflow/Voluum) → `UI_KEEP` (**fica sempre**: idioma,
  i18n, slider, accordion, cronômetro, animação, máscara, validação…) →
  `TRACKER_SRC` (padrões frouxos). Assim `/track.js` não leva junto um
  `slick-track.js`. A decisão olha a **URL de origem**, resolvida de volta a
  partir do caminho local — inclusive para `<img>` e `<iframe>`, e um
  `<iframe>` 1x1 invisível é beacon por forma, venha de onde vier.
  Opções de idioma: `--idioma <cod>` (o padrão do clone), `--idiomas a,b,c`
  (os oferecidos), `--idioma-pos bl|br|tl|tr` (canto do botão),
  `--idioma-auto` (1ª visita segue o navegador), `--sem-idiomas`.

- **`servir.py <nome> [porta]`** — serve em localhost com os MIME types certos
  (webp, webm, fontes).

## Organização

Uma pasta por site em `clones/<nome>/`, contendo `index.html`, `assets/` e
`i18n/` (`dicionarios.js` gerado + os `<código>.json` de origem), tudo com
caminhos relativos e editável à mão.

## Conferir antes de entregar

Abrir `file:///home/gustavo/clonador-paginas/clones/<nome>/index.html` e checar:
- visual idêntico ao original;
- o botão flutuante de idioma abre e cada opção troca o texto na hora,
  inclusive no celular (largura estreita);
- FAQ abrindo ao clicar, cronômetro correndo, sliders/animações rodando;
- ao passar o mouse nos `<a>`, a barra de status mostra a URL fornecida.

## Notas de ambiente

- A captura roda no navegador porque `curl`/`wget` levam 403 em páginas atrás
  de Cloudflare ou geobloqueio; o navegador herda a sessão/VPN do usuário.
- Rodar `clonar.py`/`servir.py` a partir de uma sessão automatizada pode
  esbarrar num classificador de permissão. Quando isso acontecer, entregue ao
  usuário o comando exato para ele rodar no terminal dele, e faça o que der por
  edição de arquivo. Relate com fidelidade o que rodou e o que ficou pendente.
