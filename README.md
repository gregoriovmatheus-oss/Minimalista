# Minimalista — Clipador ao vivo

Acompanha uma live da **Twitch** ou do **YouTube** e corta clipes **enquanto ela acontece**:

- **Automático pelo chat:** quando o chat explode (muito mais mensagens que o normal, `KEKW`, `kkkkk`, `POG`, `😂`, "clipa"…), salva os últimos segundos.
- **Comando no chat:** moderador ou streamer digita `!clip` e o clipe é salvo.
- **Manual:** aperte **ENTER** no terminal (pode digitar um nome antes: `jogada incrível` + ENTER).

Cada clipe sai em dois arquivos: o original e um `_vertical.mp4` (1080x1920, fundo desfocado e título em cima) pronto para TikTok, Shorts e Reels. Ficam em `clipes/`, com 30 s antes e 10 s depois do momento (configurável). O vídeo não é recodificado, então o corte é instantâneo e sem perda de qualidade.

## Instalação

Precisa de **Python 3.10+** e **ffmpeg** no PATH.

```bash
pip install -r requirements.txt
```

## Uso

```bash
# Twitch: nome do canal ou link
python -m clipador gaules
python -m clipador https://www.twitch.tv/casimiro

# YouTube: link da live, ou /@canal/live para pegar a live atual do canal
python -m clipador "https://www.youtube.com/watch?v=XXXXXXXXXXX"
python -m clipador https://www.youtube.com/@canal/live

# várias lives ao mesmo tempo (cada uma vira uma subpasta em clipes/)
python -m clipador gaules casimiro "https://youtu.be/XXXXXXXXXXX" https://www.youtube.com/@canal/live
```

Com várias lives: **ENTER** corta todas; `2` + ENTER corta só a live 2; `2 jogada absurda` + ENTER corta a live 2 com esse título.

Opções úteis:

| Opção | Padrão | O que faz |
|---|---|---|
| `--antes` / `--depois` | 30 / 10 | segundos antes e depois do momento |
| `--sensibilidade` | 2.5 | quantas vezes acima do normal o chat precisa ficar (menor = mais clipes) |
| `--minimo` | 15 | pontuação mínima na janela (aumente em chats gigantes) |
| `--intervalo` | 45 | tempo mínimo entre clipes automáticos |
| `--aquecimento` | 60 | segundos observando o chat antes do 1º corte automático |
| `--comando` | `!clip` | comando de chat para mods (`--comando ''` desliga) |
| `--sem-chat` | — | só corte manual |
| `--sem-vertical` | — | não gera a versão 9:16 |
| `-q` / `--qualidade` | best | qualidade do streamlink (`720p`, `480p`…) |
| `-o` / `--saida` | clipes | pasta de saída |

Teste sem internet usando um vídeo local como se fosse a live:

```bash
python -m clipador --fonte video.mp4
```

## Como funciona

1. `streamlink` puxa a live e o `ffmpeg` fatia em pedaços de 2 s, guardando só os últimos ~3 min em `clipes/.buffer/` (buffer circular).
2. O chat é lido sem login (IRC anônimo na Twitch, API interna do chat no YouTube). Cada mensagem vale 1 ponto, mais bônus por risadas/hype/emojis. Quando a soma dos últimos 10 s passa de 2,5× a média, marca o momento.
3. Depois de gravar os segundos "depois", junta os pedaços daquele intervalo em um `.mp4`.

O corte tem precisão de ~2 s (o tamanho de cada pedaço).

## Testes

```bash
pip install pytest
python -m pytest
```

## Rodar pelo celular (GitHub Actions)

1. Edite `lives.txt` (um link por linha) e, se quiser, `palavras.txt` (palavras do chat que indicam o momento a clipar, ex: `assalto`).
2. Faça commit: a gravação começa sozinha e dura 3 h (ou rode manualmente em **Actions → Clipador → Run workflow** e escolha os minutos).
3. Quando terminar, abra a execução em **Actions** e baixe `clipes-verticais` (prontos para postar) ou `clipes-originais`.
