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

3. **Trocar o link dos `<a>`** pela URL que o usuário fornecer — apenas os
   elementos `<a>`. O `href` visível (hover) e o clique passam a apontar para
   essa URL. Não mexer em botões que não sejam `<a>`, nem em mais nada.

## Ferramentas (em `~/clonador-paginas`)

- **`capturar.js`** — cole no Console (F12) da página já aberta no navegador;
  baixa um `.json` com o HTML e todos os assets. Roda no navegador para herdar
  a sessão e a VPN quando a página é geo-restrita.
- **`clonar.py <captura.json> <nome> [--link "<url>"]`** — reconstrói em
  `clones/<nome>/`, remove o rastreamento e, com `--link`, aponta os `<a>` para
  a URL. Imprime uma auditoria — o esperado é `faltando: 0` e
  `chamadas externas automáticas: nenhuma`.
- **`servir.py <nome> [porta]`** — serve em localhost com os MIME types certos
  (webp, webm, fontes).

## Organização

Uma pasta por site em `clones/<nome>/`, contendo `index.html` + `assets/`,
tudo com caminhos relativos e editável à mão.

## Conferir antes de entregar

Abrir `file:///home/gustavo/clonador-paginas/clones/<nome>/index.html` e checar:
- visual idêntico ao original;
- FAQ abrindo ao clicar, cronômetro correndo, sliders/animações rodando;
- ao passar o mouse nos `<a>`, a barra de status mostra a URL fornecida.

## Notas de ambiente

- A captura roda no navegador porque `curl`/`wget` levam 403 em páginas atrás
  de Cloudflare ou geobloqueio; o navegador herda a sessão/VPN do usuário.
- Rodar `clonar.py`/`servir.py` a partir de uma sessão automatizada pode
  esbarrar num classificador de permissão. Quando isso acontecer, entregue ao
  usuário o comando exato para ele rodar no terminal dele, e faça o que der por
  edição de arquivo. Relate com fidelidade o que rodou e o que ficou pendente.
