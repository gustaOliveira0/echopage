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

   **O que as listas não decidem, a LLM decide.** As listas cobrem o que já se
   conhece; um rastreador novo, ou servido de um domínio próprio, não casa com
   nada e passaria direto. Todo script que sobra sem veredicto vai numa única
   chamada `claude -p`, classificado em `interface` / `rastreamento` / `misto`,
   com a regra de ouro no prompt: **na dúvida, interface**. O veredicto é
   gravado por hash do conteúdo em `.veredictos.json`, então cada script é
   julgado uma vez só, para sempre, em qualquer clone — a segunda rodada não
   chama a LLM. `--sem-triagem` desliga.

   Foi assim que saiu o `b04jdmd.com/scripts/main.js` da Vanotium: nome
   genérico, domínio anônimo, nenhuma lista pegava — e são 202 chamadas a
   `EF.`, com `offer_id`, `transaction_id` e `fingerprint`.

   **Global órfão vira stub.** Tirar o SDK e deixar o JS de interface chamando
   `EF.click()` dá `ReferenceError`, e o erro derruba o resto do arquivo — a
   página perde justamente a UI que a limpeza queria proteger. Todo global que
   o JS mantido chama, não define, e que o JS removido definia, ganha um objeto
   inerte com os métodos certos.

3. **Todo clone sai traduzido nos idiomas pedidos.** No comando entram os
   idiomas; o **primeiro é o padrão** e todos ficam disponíveis para trocar
   no site:

   ```
   ./clonar.py captura.json nome --link "<url>" --idiomas "pt-br,en,de"
   ```

   O botão de troca é injetado pelo clonador — a página pode ter um seletor
   ou não. É um botão flutuante isolado em Shadow DOM, responsivo, que não
   depende do CSS nem do JS do site. A troca é na hora, trocando o texto pelo
   dicionário: sem recarregar, sem query string, sem servidor, sem chamada
   externa. A escolha do visitante fica no `localStorage`.

   **O idioma de origem vem sempre da própria página**, nesta ordem: `lang`
   do `<html>`, `xml:lang`, `<meta http-equiv="content-language">`,
   `<meta name="language">`, `og:locale` — aceitando aspas simples, duplas ou
   nenhuma, e normalizando (`pt_BR` → `pt-br`). Se o HTML não declarar nada,
   o idioma é detectado a partir do texto que ele contém. Nunca um padrão
   chutado: dizer "é português" para uma página em inglês faria o clonador
   traduzir de um idioma para ele mesmo. `--idioma-origem` existe só para o
   caso raro de o site declarar errado.

   Todo idioma pedido que não seja o da página ganha dicionário, nesta ordem
   de fonte:

   a. **A versão que o site de origem devolveu.** Muitas dessas páginas
      traduzem no servidor (`?lang=en`), e isso não vem no HTML baixado. O
      `capturar.js` detecta o seletor nativo e busca cada versão por `fetch`
      same-origin — de dentro da página ele leva o cookie do Cloudflare e
      passa onde `curl` leva 403. O `clonar.py` casa original com traduzida
      (mesmo template, mesma ordem de texto). Autêntico e de graça.
   b. **`i18n/<código>.json` já na pasta** — cache das rodadas anteriores,
      editável à mão (chave = texto original, valor = tradução).
   c. **Tradução na hora**, chamando `claude -p` em lotes de 40 termos, com
      conferência chave a chave e uma segunda tentativa para o que faltar. O
      resultado é salvo como `i18n/<código>.json`, então só se paga uma vez.
      `--sem-traduzir` desliga.

   **Qualquer sigla BCP-47 serve** — `sw`, `vi`, `ar`, `sr-latn`. Não há
   lista fechada: o nome no menu sai do `Intl.DisplayNames` do navegador, no
   próprio idioma ("Kiswahili", "العربية", "日本語"), e idioma de escrita da
   direita para a esquerda (ar, he, fa, ur…) ganha `dir="rtl"` no `<html>`.
   Sigla malformada para o comando antes de gastar tradução.

   **Peso.** Um idioma de landing típica dá ~15 KB (~6 KB gzip) — menos que
   um ícone, contra os ~34 MB de imagens e vídeo de uma página dessas. Por
   isso os dicionários vêm embutidos por padrão: a troca é instantânea e não
   pede nada ao servidor. Passando de 120 KB somados (páginas de texto longo
   com muitos idiomas), o clonador troca sozinho para um arquivo por idioma,
   buscado no primeiro clique via `<script src>` — que funciona até em
   `file://`, onde um `fetch` de `.json` morre em CORS. A saída diz qual modo
   usou.

   Uma landing típica dá ~150 termos: ~2 min por idioma. Rótulo de idioma
   ("English", "日本語") não entra — cada um já está no próprio idioma.

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
  Opções de idioma: `--idiomas a,b,c` (disponíveis; o 1º é o padrão),
  `--idioma-origem <cod>` (idioma da página capturada), `--sem-traduzir`,
  `--idioma-pos bl|br|tl|tr` (canto do botão), `--idioma-auto` (1ª visita
  segue o navegador), `--sem-idiomas`.

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
