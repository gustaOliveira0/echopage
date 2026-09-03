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

   **Quem troca o idioma é o seletor que a página já tem** — o clonador não
   injeta botão nenhum. Ele só marca as opções nativas com `data-clone-lang`
   e passa a escutar o clique (e o `change`, quando o seletor é um `<select>`).
   A troca é na hora, trocando o texto pelo dicionário: sem recarregar, sem
   query string, sem servidor, sem chamada externa. A escolha do visitante
   fica no `localStorage`.

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

4. **Mandar toda navegação para a URL fornecida** (`--link`). Estas páginas
   são pre-sell: **toda saída vai para a oferta**, e não existe outro destino.

   A separação que vale é **`<a>` contra o resto**:

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
  `--sem-idiomas`.

- **`verificar.py [nome|pasta|arquivo.zip]`** — diz se o clone está inteiro,
  sem abrir o navegador. Sem argumento, confere todos. Sai com código 1 se
  achou buraco. É a MESMA função que o `clonar.py` roda no fim e que o painel
  usa no selo da lista — um veredicto só, nunca dois.
  Confere: (a) toda referência local de todo HTML **e de todo CSS**, resolvida
  contra o arquivo que cita (absoluta `/x.png` contra a raiz do clone);
  (b) chamadas externas automáticas; (c) `<a>` que não vão para a oferta;
  (d) opções de idioma marcadas.
  O que já dava 404/403 na origem aparece à parte e **não** conta como falha —
  o clone não mostrar o que o original também não mostra é fidelidade.

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

Depois o que só o olho vê — abrir
`file:///home/gustavo/clonador-paginas/clones/<nome>/index.html` e checar:
- visual idêntico ao original;
- o seletor de idioma da própria página troca o texto na hora, inclusive no
  celular (largura estreita);
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
