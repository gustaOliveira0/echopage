# echopage

Clona uma landing page inteira para rodar em `localhost` — HTML, CSS, imagens,
vídeos e fontes — removendo o rastreamento, apagando os comentários e mandando
toda a navegação para o seu link de afiliado.

Feito para páginas de *pre-sell*: o resultado é uma pasta (ou um `.zip`) que
abre offline, não telefona para ninguém, e onde **todo botão leva à oferta**.

```
python3 painel.py          →  http://localhost:7000
```

Cola o link do site, cola o link de afiliado, aperta **Clonar**. O log aparece
ao vivo e no fim você abre no navegador ou baixa o `.zip`.

---

## As três paredes

Elas são independentes, e confundi-las custa tempo:

| parede | sintoma | o que resolve |
|---|---|---|
| **Sem monitor** | precisa de tela para o Chrome | `--xvfb` — tela virtual. **Não** é headless |
| **Desafio** | `Um momento…`, verificação em JS | `--visivel` uma vez; o cookie fica no perfil |
| **Bloqueio / geo** | `Sorry, you have been blocked` | trocar o IP: `--proxy` ou VPN de sistema |

O Chrome **headless não passa** pelo Cloudflare — nem com o cookie salvo, porque
o que ele detecta é o modo headless em si. O Xvfb tira o monitor **sem** ligar o
headless, e por isso passa. Verificado com perfil zerado:

```
--headless  perfil novo     ->  'Um momento…'        (desafio)
--headless  perfil quente   ->  'Um momento…'        (o cookie não salva)
--xvfb      perfil novo     ->  página completa      ✓
```

VPN de extensão costuma exigir clique em "conectar" a cada sessão do navegador,
o que não funciona em automação. Proxy ou VPN de sistema resolvem de vez.

---

## Instalação

Só Python 3 e Google Chrome. **Nenhuma dependência para instalar.**

Para rodar sem monitor (servidor, container, ou só para não ver janela):

```bash
sudo apt install -y xvfb
```

---

## Uso

### Pelo painel (recomendado)

```bash
python3 painel.py            # http://localhost:7000
```

Tem campo de proxy, botão para configurar a VPN no navegador da automação,
conferência do IP de saída, log ao vivo, lista dos clones e download do `.zip`.

### Pela linha de comando

```bash
# captura + clone num comando só
python3 capturar.py "https://site.com/oferta" --xvfb \
        --clonar meusite --link "https://rede.com/ABC/?uid=1"

# só servir um clone que já existe
python3 servir.py meusite 8080
```

Opções de captura que importam:

| opção | para quê |
|---|---|
| `--xvfb` | tela virtual — máquina sem monitor |
| `--visivel` | janela real — passar por desafio interativo uma vez |
| `--proxy URL` | sai por um proxy; aceita `http://usuario:senha@host:porta` |
| `--pais XX` | para antes se o IP de saída não for desse país |
| `--configurar` | abre o perfil da automação para instalar a VPN |
| `--conferir-ip` | mostra de que IP/país o navegador está saindo |

---

## O que o clone garante

**Zero chamadas externas.** Depois da limpeza, qualquer tag que ainda buscaria
algo de fora sozinha é cortada — seja rastreador que ninguém reconheceu, seja
asset que não veio no download. `<a href>` não é tocado: clicar continua livre.

**Nenhum comentário HTML.** Some tudo. Além de não servir para nada num clone,
um `<script>` comentado quebrava o pareamento do regex e deixava passar o
tracker seguinte.

**Toda navegação vai para o seu link.** A regra é `<a>` contra o resto:

- um **`<a>` é um link** — header, rodapé, "Política de privacidade", `#` pelado,
  `javascript:void(0)`, relativo, absoluto: tudo vai para a oferta, e o `href`
  visível no hover também;
- **`<button>` e `<div onclick>`** passam pelo filtro de interface — accordion,
  slider, aba, som, hambúrguer, cronômetro ficam;
- **fica de fora só** o que não sai da página: `<a href="#secao">` cuja seção
  existe de fato, e o seletor de idioma.

`javascript:void(0)` e `#` pelado **não são âncoras** — são o placeholder de
botão que navega por JS. Tratá-los como internos deixava os CTAs mudos.

**O frontend continua vivo.** FAQ, cronômetro, slider, animações, máscaras,
validação: tudo preservado. Quando as listas não sabem decidir um script, a
pergunta vai para uma LLM (`claude -p`), com "na dúvida, é interface" como regra
de ouro — e o veredicto fica em cache por hash, julgado uma vez para sempre.

**Idiomas, se a página tiver.** Página com seletor nativo sai com exatamente os
idiomas que ela oferecia, e o **botão original dela** passa a trocar o texto na
hora, sem recarregar. Página de um idioma só não ganha nada.

---

## Arquivos

| | |
|---|---|
| `painel.py` | interface web, log ao vivo, serve clones, entrega o `.zip` |
| `capturar.py` | dirige um Chrome real por CDP e captura sozinho |
| `capturar.js` | a captura em si, injetada na página |
| `cdp.py` | cliente WebSocket/CDP mínimo, só stdlib |
| `proxyauth.py` | encaminhador para proxy com usuário e senha |
| `clonar.py` | limpeza, tracking, idiomas, links, auditoria |
| `servir.py` | serve um clone com os MIME types certos |

Cada clone vira `clones/<nome>/` com `index.html`, `assets/` e — quando há
idiomas — `i18n/`. Uma ficha `.clone.json` registra origem, data, link e comando;
ela **não** vai no `.zip`.

---

## Auditoria

Toda montagem termina com um relatório. O esperado:

```
assets referenciados no HTML: 55 | faltando: 0
chamadas externas automáticas: nenhuma  [OK]
comentários HTML removidos: 12
1 link(s) de navegação apontam para fora (só ao clicar):
     - https://rede.com/ABC/?uid=1
```

`faltando` só deve ter o que já dava 404 no site de origem — o relatório separa
os dois casos.

---

## Limites conhecidos

- **A captura precisa do Chrome.** Não existe caminho por `curl`: páginas atrás
  de Cloudflare respondem 403 a qualquer coisa que não seja navegador.
- **Desafio interativo** ("verifique se você é humano") precisa de um clique
  humano uma vez, com `--visivel`. Não há contorno de detecção de bot aqui.
- **Bloqueio por IP** só se resolve trocando de saída.
- **Proxy autenticado** foi validado contra um proxy local de teste; provedores
  que rotacionam IP por conexão podem quebrar a sessão do Cloudflare no meio.
