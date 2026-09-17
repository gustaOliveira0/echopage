# Projeto: echopage (clonador de páginas)

Clonar uma landing page e servi-la em `localhost` preservando todo o visual e a
interatividade, removendo apenas o rastreamento, e (quando pedido) apontando os
links `<a>` para uma URL fornecida.

## Escopo exato — faça isto, nada além

1. **Manter todas as características visuais e de frontend.**
   Layout, CSS, imagens, vídeos, fontes e todo o JavaScript de interface:
   FAQ accordion, cronômetro/countdown, sliders/carrosséis, animações, menu,
   máscaras, validação de formulário, datas dinâmicas. A página deve ficar
   visualmente idêntica e funcional.

   **O clone parte do HTML que o SERVIDOR mandou, não do renderizado.** O
   `outerHTML` do fim da captura é a página depois do JavaScript: o
   carrossel já duplicou e reordenou os slides, o letreiro já se copiou, a
   animação de entrada já terminou. No clone esse mesmo JS roda de novo por
   cima — foi a galeria da Guardality abrindo fora de ordem e com foto
   repetida. O `capturar.js` busca a própria URL de dentro da página (com o
   cookie dela, passa pelo Cloudflare) e passa pelo `DOMParser`, que
   interpreta sem rodar script e serializa com aspas duplas, a forma que a
   limpeza lê. O JS do clone então faz o que fez no original: uma vez só.
   O renderizado fica de reserva quando o original não serve — captura
   antiga, bloqueio/desafio no lugar da página, ou casca de SPA (o original
   com menos da metade do texto) — e aí as cópias de slide
   (`glide__slide--clone`, `slick-cloned`, `swiper-slide-duplicate`…) saem
   antes. A saída do `clonar.py` diz qual base usou.

   E o `<!DOCTYPE>` vai junto: o `outerHTML` não o traz, e sem ele o clone
   abria em modo quirks, com outra altura de linha e outra caixa.

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

   **Completude: o que o navegador carregou não é tudo que a página usa.**
   Três ausências custaram imagens de verdade, e as três somem sem deixar
   rastro:

   a. **O buffer de recursos do Chrome guarda 250 entradas** e descarta o
      resto calado. Numa landing de 400 arquivos o que cai fora é o fim da
      fila — justamente a imagem e o vídeo que a rolagem acabou de carregar.
      O `capturar.py` instala, **antes** da página, um observador sem teto
      (`Page.addScriptToEvaluateOnNewDocument`), e a captura soma as duas
      fontes.
   b. **O checkout não está no HTML.** Ele chega por AJAX, como um pedaço
      de markup servido de um `.php`, e é ele que traz os `<img>` do
      formulário (bandeira de cartão, cadeado, selo de desconto), o `<link>`
      do CSS dele e as bandeirinhas do seletor de telefone. Ninguém abriu o
      formulário, então o navegador nunca pediu nada disso. Como o pedaço é
      HTML de verdade, as referências dele valem para qualquer extensão — e
      o `clonar.py` reescreve os caminhos **dentro** do fragmento, contra a
      raiz do clone, que é onde ele vai ser injetado. Na Melara Max isso
      eram 43 arquivos e 1310 referências que o clone não tinha.
   c. **Slider e galeria guardam a lista de imagens num array de JS**, e
      vídeo de modal só ganha `src` no clique. Aí o caminho é texto solto:
      só entra o que **termina** em extensão de mídia, senão qualquer string
      viraria candidata.
   d. **O vídeo mora noutro domínio, e o `fetch` não pode lê-lo.** O
      navegador BAIXA e TOCA `video.<site>/x.mp4` na tela, mas sem
      cabeçalho de CORS ele recusa entregar os bytes ao JavaScript — no log
      da captura isso é só `ERR`, que parece falha de rede e não é. Foram
      os 8 vídeos da Fungabeam sumindo sem uma linha de aviso. O
      `capturar.py` refaz esses pedidos **pelo terminal**, onde CORS não
      existe, e costura o resultado no `.json` da captura. Só o que falhou
      por erro: o que respondeu 404/403 é ausência da origem.
   e. **O que só o clique carrega.** O joinha ativo do comentário
      (`thumb_up-active.svg`) nasce de um `replace` no nome do passivo: não
      está no HTML, no CSS nem inteiro no JS. A sonda de cliques (item 4)
      clica em cada botão, e o que o navegador pede nesse clique entra na
      captura.

   Some a isso o estilo calculado (que é a única fonte de `::before`/
   `::after`) e as regras em memória (que é a única fonte do `<style>` do
   HTML e da folha que o `fetch` não consegue ler). Nada disso substitui a
   rolagem — ela continua sendo o que dispara o lazy-load.

   **Nome não decide o que é rastreamento quando o arquivo é mídia.** Barrar
   `hero-pixel.png`, ou uma imagem servida pelo redimensionador da
   Cloudflare (`/cdn-cgi/image/…`), deixa buraco na página; baixar à toa um
   `.gif` de 1x1 de tracking não custa nada, porque o beacon sai pela
   **forma**. Sob `/cdn-cgi/` a Cloudflare serve medição (`rum`, `beacon`,
   `zaraz`) e também **interface** — o `email-decode.min.js`, que só
   desembaralha o e-mail para ele aparecer. Barrar o caminho inteiro era
   largo demais.

   **Nem todo endereço no HTML é um endereço.** `"${imgUrl}"`,
   `"+cImageSrc+"` e `"null"` são o molde do JavaScript que não foi
   preenchido. Buscá-los traz a **página de erro** do site com status 200,
   ela entra no clone como asset, e a conferência passa a cobrar as
   referências da página de erro — foi assim que 20 fontes de um Font
   Awesome que a página nunca usou viraram "buraco" num clone correto. Pela
   mesma razão, página inteira de OUTRO domínio (o link que a captura
   seguiu) não é asset: é destino, e fica de fora.

   **E o mesmo endereço aparece escrito de dois jeitos.** O HTML traz o
   nome como o autor digitou — `1_Stops Most Advanced Scanners.mp4`,
   `Card &amp; Data.mp4` — e a captura grava como o navegador pediu, com
   `%20`. Sem casar as duas formas, os dois vídeos da Guardality ficaram
   apontando para fora e o corte de chamada externa os desligou.

   **E o nome do arquivo mente sobre o que ele é.** O CDN da Dreamzy serve
   um PNG de 1017x1017 com o nome `moneyback.svg`. Na origem isso passa
   despercebido — o servidor manda `Content-Type: image/png` junto e o
   navegador obedece ao cabeçalho. No clone quem diz o tipo é a extensão
   do arquivo no disco, e `.svg` vira `image/svg+xml`: o navegador tenta
   ler o PNG como XML, não casa (SVG não se fareja: ou é XML válido ou não
   é nada) e a tela fica com o quadro vazio da imagem quebrada. Eram três
   arquivos e quatro imagens — o selo da garantia, a elipse do fundo e o
   logotipo do topo —, e o `verificar.py` dizia `CLONE ÍNTEGRO`, porque
   estar no disco elas estavam. Por isso o nome local sai da **assinatura
   dos bytes**, não da URL: PNG, JPEG, GIF, WEBP, AVIF, ICO, MP4, WEBM,
   WOFF/WOFF2, TTF/OTF. Só assinatura binária entra nessa conta — nenhuma
   delas casa com HTML, CSS ou JS, e é isso que mantém o fragmento de
   checkout servido por um `.php` sendo tratado como texto.

   **E só troca de FAMÍLIA conta.** Entre imagens rasterizadas o navegador
   fareja e mostra assim mesmo: na Guardality são 36 arquivos WEBP e AVIF
   com nome `.png` e `.jpg`, e os 36 aparecem na tela. Renomear aquilo era
   agitação, e cobrar aquilo no `verificar.py` era alarme falso. O que
   quebra é o arquivo mudar de família — imagem virando vetor, fonte,
   vídeo —, e o caso clássico é o SVG, o único que não se fareja.

   O `verificar.py` passou a cobrar isso, e é essa a calibragem que impede
   a reincidência: o defeito não era só a imagem sumida, era ela sumir com
   o clone assinado como íntegro. Nomear o arquivo pelo que ele é e cobrar
   que ele seja são a mesma pergunta, então é uma função só
   (`verificar.extensao_errada`), lida pelos dois lados.

   **Remontar tem de partir do zero.** A pasta `assets/` é apagada antes de
   cada montagem. Sem isso o arquivo de uma captura antiga fica para trás e
   reaparece como referência quebrada de um clone que já está certo. E a
   captura, ao contrário, **fica guardada** em `.capturas/<nome>/`: ela é o
   passo caro e frágil (Chrome, VPN, Cloudflare), e remontar o clone com uma
   correção do clonador não pode exigir capturar de novo — num site
   geobloqueado pode não haver segunda chance.

   **A prova é comparar com o original.** Abrir os dois no mesmo navegador,
   rolar até o fim e contar a mídia pedida: os números têm de bater. Na
   Melara Max são 68 dos dois lados — o original pede 95 recursos e o clone
   77, e a diferença é exatamente o rastreamento removido.

3. **Todo clone sai traduzido nos idiomas pedidos.** No comando entram os
   idiomas; o **primeiro é o padrão de reserva** e todos ficam disponíveis
   para trocar no site:

   ```
   ./clonar.py captura.json nome --link "<url>" --idiomas "pt-br,en,de"
   ```

   **Quem troca o idioma é o seletor que a página já tem** — o clonador não
   injeta botão nenhum. Ele só marca as opções nativas com `data-clone-lang`
   e passa a escutar o clique (e o `change`, quando o seletor é um `<select>`).
   A troca é na hora, trocando o texto pelo dicionário: sem recarregar, sem
   query string, sem servidor, sem chamada externa. A escolha do visitante
   fica no `localStorage`.

   O texto que o JavaScript da página escreve **depois** também troca: o
   "Load More" que vira "Load Less", a avaliação que chega por AJAX, o
   modal que abre. Um observador de mutações põe esse texto na lista e o
   traduz — e separa a troca da página da nossa, senão um desfaria o outro.

   **Em que idioma a página abre é o lugar do visitante que decide.**
   Quem acessa dos EUA abre em inglês, do Brasil em português, da
   Alemanha em alemão — sem clicar em nada. Só o que o clone tem entra
   na conta: país cujo idioma o clone não oferece abre no primeiro da
   lista, e `pt` serve para quem só tem `pt-br` (recusar seria mandar
   inglês para Portugal).

   **A decisão é tomada no navegador, antes de desenhar — a página nunca
   espera rede para abrir.** O lugar sai do fuso horário
   (`Intl.DateTimeFormat().resolvedOptions().timeZone`): o navegador
   responde na hora, offline, e "America/New_York" diz o mesmo que uma
   consulta de IP diria. A tabela fuso→país é gerada do `zone.tab` do
   sistema e mora em `zonas.py`, fora do código; no clone ela sai
   filtrada pelos idiomas dele (uns 5 KB para `pt-br,en`, contra os
   ~34 MB de mídia).

   A ordem de quem manda é esta, e ela não inverte:

   1. **A escolha do visitante**, se ele já trocou o idioma alguma vez.
      Escolher à mão grava no `localStorage`, e a partir daí nada mais
      opina — quem clicou em "English" não quer voltar ao português na
      próxima visita.
   2. **O lugar, pelo fuso horário.** Instantâneo e sem requisição.
   3. **O idioma do navegador** (`navigator.languages`), quando o fuso
      não leva a nada que o clone tenha — japonês num clone `pt-br,en`
      com navegador em inglês abre em inglês.
   4. **O idioma da própria página.**

   O fuso do Brasil está escrito na tabela mesmo dando no idioma padrão,
   e isso é de propósito: sem a linha, quem está no Brasil com o
   navegador em inglês cairia na regra 3 e abriria em inglês — o lugar,
   que é quem devia mandar, teria sido ignorado.

   **O IP entra depois, só confirmando.** Por padrão o clone tenta
   `/cdn-cgi/trace` no próprio domínio: é same-origin, responde do edge
   da Cloudflare quando o site está atrás dela, e não é chamada a
   terceiro — em qualquer outro lugar dá 404 e acaba ali. `--geo-ip`
   acrescenta `get.geojs.io`, `ipwho.is` e `ipapi.co`, na ordem, 2,5 s
   de paciência cada. Vale para tráfego com muita VPN, onde o fuso e o
   IP discordam. **Esses 2,5 s são do visitante, não da clonagem, e
   nada na tela espera por eles**: a página já abriu no idioma certo, e
   a resposta só corrige se discordar. O país fica uma semana no
   `localStorage` — uma consulta por visitante, não uma por página.

   `--sem-geo` desliga tudo e todo mundo abre no primeiro idioma.

   **O idioma de origem vem sempre da própria página**, nesta ordem: `lang`
   do `<html>`, `xml:lang`, `<meta http-equiv="content-language">`,
   `<meta name="language">`, `og:locale` — aceitando aspas simples, duplas ou
   nenhuma, e normalizando (`pt_BR` → `pt-br`). Se o HTML não declarar nada,
   o idioma é detectado a partir do texto que ele contém — **primeiro no
   próprio clonador**, pela escrita (kana, hangul, cirílico, árabe…) e pelas
   palavras-função, e só depois, se isso não decidir, perguntando à LLM.
   Nunca um padrão chutado: dizer "é português" para uma página em inglês
   faria o clonador traduzir de um idioma para ele mesmo; não saber é
   resposta legítima. `--idioma-origem` existe só para o caso raro de o site
   declarar errado.

   **E não saber o idioma nunca derruba a clonagem.** A
   get-dreamhumidifier não declara `lang` e não tem seletor — não havia uma
   palavra a traduzir — e mesmo assim o clone não chegou a existir: o
   clonador saía com `ERRO: a página não declara idioma` antes de escrever o
   `index.html`. São duas coisas separadas, e a segunda não pode matar a
   primeira. Por isso: sem outra versão para casar, o idioma de origem não
   muda nada do que vai para o disco e ninguém pergunta à LLM (que no
   servidor nem existe — lá não há CLI do `claude`); havendo tradução em
   jogo e ainda assim não dando para detectar, sai um aviso dizendo para
   remontar a mesma captura com `--idioma-origem`, e o clone sai inteiro,
   só sem o sistema de idiomas.

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

4. **Mandar toda navegação para a URL fornecida** (`--link`). Estas páginas
   são pre-sell: **toda saída vai para a oferta**, e não existe outro destino.

   **Acima de nome e de tag, vale o que o botão FAZ.** Nome engana: o "Load
   More" das avaliações da Guardality tem a classe `cta` e só abre a lista;
   o joinha do comentário é um `<button>` solto que só troca o ícone; a
   seta do carrossel de depoimentos fica fora do carrossel. O filtro por
   nome mandava os três para a oferta. Por isso, depois da captura, o
   `sondar.js` **clica de verdade** em cada botão distinto da página, com
   toda saída trancada (API `navigate` na página, `Fetch` barrando o
   documento principal, janela nova fechada), e anota:

   - tentou sair (navegar, abrir janela, enviar formulário) → **saída**:
     vai para a oferta, mesmo dentro de um slider;
   - mudou a página sem sair dela → **interface**: fica, tenha o nome que
     tiver, inclusive se for `<a>`;
   - não fez nada → vale a regra por nome, abaixo.

   O que muda sozinho não conta como efeito: o que se repete na
   observação inicial (cronômetro, letreiro) e o que mudou nos 450 ms
   antes do clique. Autoplay de carrossel mexe nos mesmos nós que a seta,
   por isso nada disso é desconto permanente — e quando tudo o que mudou
   foi um carrossel que não contém o botão, a sonda clica de novo para
   confirmar. O veredito vai no `.json` (`acoes`) e o clone casa cada
   clique por tag, id, classes (sem as de estado, `--active` incluso),
   texto e classe do pai.

   Para o que a sonda não alcançou, a separação por nome é **`<a>` contra o
   resto**:

   - Um **`<a>` é um link** — tira o visitante da página, então vai para a
     oferta. Vale para header, rodapé, "Política de privacidade", "Termos",
     "Fale conosco", `href` relativo, absoluto, `#` pelado e
     `javascript:void(0)`. O `href` visível (hover) também muda.
   - **`<button>`, `<div onclick>` e afins** passam pelo filtro de interface:
     accordion, slider, aba, hambúrguer, som, zoom, galeria e cronômetro
     ficam; o resto vai para a oferta.
   - **Fica de fora só** o que não sai da página: `<a href="#secao">` cuja
     seção existe de fato (rolagem interna, accordion do Bootstrap) e o
     seletor de idioma. `--sem-ancoras` manda até essas para a oferta.
   - Submit de formulário vai para a oferta.

   Atenção ao caso que já custou caro: `javascript:void(0)` e `#` pelado
   **não são âncoras** — são o placeholder clássico de botão que navega por
   JS. Tratá-los como "interno" deixou os 8 CTAs da Fungabeam mudos. E o
   filtro de interface **não pode** valer para `<a>`: um link de header
   dentro de `.menu` precisa redirecionar do mesmo jeito.

## Ferramentas (em `~/clonador-paginas`)

**O caminho normal é o painel** — o produto se chama **echopage**.
`./painel.py` → `http://localhost:7000`:
cola o link do site e o de afiliado, acompanha o log ao vivo, abre o clone
ou baixa o `.zip`. Os scripts abaixo são as peças que ele orquestra.


- **`painel.py [porta]`** — painel local (padrão 7000). Roda a rotina
  inteira, mostra o log ao vivo, serve os clones em `/c/<nome>/` e entrega o
  `.zip`. Tem seção de VPN/proxy e botão para configurar o navegador.
- **`capturar.py <url>`** — dirige um Chrome de verdade por CDP e captura
  sozinho, sem colar nada no console. Opções: `--xvfb` (tela virtual, para
  máquina sem monitor), `--visivel` (janela real, para passar por desafio
  interativo uma vez), `--proxy` (aceita usuário e senha), `--pais XX` (para
  se o IP de saída não for desse país), `--configurar` (abre o perfil da
  automação para instalar a VPN), `--conferir-ip`, `--clonar <nome>`.
- **`cdp.py`** — cliente WebSocket/CDP mínimo, só stdlib.
- **`proxyauth.py`** — o Chrome ignora credencial em `--proxy-server`; este
  encaminhador local sem senha repassa para o proxy real já autenticado.
- **`capturar.js`** — a captura em si, injetada na página pelo `capturar.py`.
  Também dá para colar no Console (F12) à mão, se preferir.
- **`sondar.js`** — a sonda de cliques, injetada pelo `capturar.py` depois
  da captura: clica em cada botão com a saída trancada e diz se ele é
  interface, saída ou nada (item 4). Colado à mão, o `capturar.js` não
  sonda — aí os botões ficam com a regra por nome.
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
  Opções de idioma: `--idiomas a,b,c` (disponíveis; o 1º é o de reserva,
  porque o de entrada sai do lugar do visitante), `--sem-geo` (todo mundo
  abre no 1º), `--geo-ip` (confirma o lugar por consulta de IP),
  `--idioma-origem <cod>` (idioma da página capturada), `--sem-traduzir`,
  `--sem-idiomas`.

- **`verificar.py [nome|pasta|arquivo.zip]`** — diz se o clone está inteiro,
  sem abrir o navegador. Sem argumento, confere todos. Sai com código 1 se
  achou buraco. É a MESMA função que o `clonar.py` roda no fim e que o painel
  usa no selo da lista — um veredicto só, nunca dois.
  Confere: (a) toda referência local de todo HTML, **de todo CSS** e **de
  todo fragmento** (o pedaço de markup servido de um `.php`), resolvida
  contra o arquivo que cita — o fragmento contra a raiz do clone, porque é
  lá que ele é injetado; (b) que nenhum arquivo do `assets/` esconda o
  conteúdo atrás de uma extensão de outra família (o PNG chamado `.svg`);
  (c) chamadas externas automáticas; (d) `<a>` que não vão para a oferta;
  (e) opções de idioma marcadas e como o idioma de entrada é escolhido.
  O que já dava 404/403 na origem aparece à parte e **não** conta como falha —
  o clone não mostrar o que o original também não mostra é fidelidade.

- **`conferir.py <nome>`** — abre o clone **e o original** num Chrome de
  verdade, rola os dois até o fim e compara o que cada um pediu. Sai com
  código 1 se achou problema.
  É outra pergunta, não a mesma do `verificar.py`, e a diferença já custou
  imagem: o `verificar.py` pergunta "todo arquivo citado existe no disco?",
  e aqui a pergunta é "a página pede as mesmas coisas que a original
  pedia?". Um asset pode estar no disco sem ninguém citá-lo, e uma imagem
  que só o JS conhecia some junto com o script que a citava — nos dois
  casos o `verificar.py` diz `CLONE ÍNTEGRO` e falta imagem na tela.
  Foi assim que apareceram, num clone que já passava, o bundle **inline**
  de 60 KB do VWO ainda telefonando para `visualwebsiteoptimizer.com`, o
  `SyntaxError` que ele deixava, e o `fonts.googleapis.com` que um script
  de UI injetava depois do load.
  A diferença esperada no total de recursos é exatamente o rastreamento:
  o original pede mais, e o que ele pede a mais são os trackers. O que ele
  pede e o clone não é separado em três, e **só a terceira reprova**:
  saiu de propósito (é tracker) / está no clone, só não foi pedido nesta
  visita / não pediu e não tem. Chamada externa também é separada: a de
  rastreamento reprova, a que é função (a API de preços da própria loja,
  por exemplo) vira aviso, para você decidir.

- **`zonas.py`** — tabela fuso horário → país, gerada do `zone.tab` do
  sistema (base IANA). É só dado: mora fora do `clonar.py` para não afogar
  o código, e serve para o clone saber de onde vem o visitante sem
  perguntar a ninguém. `python3 -c "import zonas; zonas.regerar()"`
  imprime a versão nova quando a base IANA mudar.

- **`servir.py <nome> [porta]`** — serve em localhost com os MIME types certos
  (webp, webm, fontes).

## Organização

Uma pasta por site em `clones/<nome>/`, contendo `index.html`, `assets/` e
`i18n/` (`dicionarios.js` gerado + os `<código>.json` de origem), tudo com
caminhos relativos e editável à mão.

## Conferir antes de entregar

Primeiro o que a máquina vê — `./verificar.py <nome>` tem de terminar em
`CLONE ÍNTEGRO`. Ele existe porque a auditoria antiga contava só os assets
citados no HTML e dizia `faltando: 0` com 12 imagens de fundo ausentes:
**imagem de fundo mora dentro do CSS**, e era exatamente ali que ninguém
olhava.

Depois `./conferir.py <nome>`, que abre o clone e o original lado a lado e
tem de terminar em `CLONE FIEL`. `CLONE ÍNTEGRO` só promete que todo
arquivo citado existe; um clone pode estar íntegro e mesmo assim ter
perdido a imagem que só o JS citava, ou continuar telefonando para um
rastreador que veio inline. Essa segunda passada é a que pega isso, e ela
precisa de rede — a página original tem de abrir.

Depois o que só o olho vê — abrir
`file:///home/gustavo/clonador-paginas/clones/<nome>/index.html` e checar:
- visual idêntico ao original — inclusive a **ordem** dos slides do
  carrossel, sem foto repetida;
- botão de interface (like, "carregar mais", seta de carrossel) funciona
  e não leva para a oferta;
- o seletor de idioma da própria página troca o texto na hora, inclusive no
  celular (largura estreita);
- o idioma de entrada segue o lugar: limpando o `localStorage` e
  recarregando, a página abre no idioma de onde se acessa — e abre já
  nele, sem piscar no idioma antigo;
- FAQ abrindo ao clicar, cronômetro correndo, sliders/animações rodando;
- ao passar o mouse nos `<a>`, a barra de status mostra a URL fornecida.

## As três paredes, e o que resolve cada uma

Confundi-las custou tempo. São independentes:

| parede | sintoma | o que resolve |
|---|---|---|
| **Sem monitor** | precisa de tela para o Chrome | `--xvfb` (tela virtual; **não** é headless) |
| **Desafio** | `'Um momento…'`, verificação em JS | `--visivel` uma vez; o cookie fica no perfil |
| **Bloqueio/geo** | `'Sorry, you have been blocked'` | trocar o IP: `--proxy` ou VPN de sistema |

Headless puro **não passa** pelo Cloudflare, nem com cookie salvo — o que
ele detecta é o modo headless. Xvfb tira o monitor sem ligar o headless, e
por isso passa. VPN de extensão costuma exigir clique em "conectar" a cada
sessão do navegador, o que não funciona em automação; proxy ou VPN de
sistema resolvem de vez.

## Notas de ambiente

- A captura roda no navegador porque `curl`/`wget` levam 403 em páginas atrás
  de Cloudflare ou geobloqueio; o navegador herda a sessão/VPN do usuário.
- Rodar `clonar.py`/`servir.py` a partir de uma sessão automatizada pode
  esbarrar num classificador de permissão. Quando isso acontecer, entregue ao
  usuário o comando exato para ele rodar no terminal dele, e faça o que der por
  edição de arquivo. Relate com fidelidade o que rodou e o que ficou pendente.
