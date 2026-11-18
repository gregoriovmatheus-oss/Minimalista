"""Leitura anônima do chat de uma live do YouTube (API interna "innertube").

Não usa chave de API nem login: faz o mesmo que a janela de chat do navegador.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.request
from typing import Any, Iterator
from urllib.parse import parse_qs, urlparse

from .chat import ChatMessage

log = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Cookie": "CONSENT=YES+1; SOCS=CAI",  # pula a tela de consentimento da UE
}
_VIDEO_ID = re.compile(r"^[\w-]{11}$")


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def _post_json(url: str, body: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={**HEADERS, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def video_id_from_url(url: str) -> str | None:
    """Extrai o ID de watch?v=, youtu.be/, /live/ID ou /shorts/ID."""
    if _VIDEO_ID.match(url):
        return url
    u = urlparse(url if "://" in url else "https://" + url)
    if u.hostname and u.hostname.endswith("youtu.be"):
        vid = u.path.strip("/").split("/")[0]
        return vid if _VIDEO_ID.match(vid) else None
    q = parse_qs(u.query)
    if "v" in q and _VIDEO_ID.match(q["v"][0]):
        return q["v"][0]
    parts = [p for p in u.path.split("/") if p]
    if len(parts) == 2 and parts[0] in ("live", "shorts", "embed") and _VIDEO_ID.match(parts[1]):
        return parts[1]
    return None


def resolve_video_id(url: str) -> str:
    """Também aceita youtube.com/@canal/live: abre a página e acha a live atual."""
    vid = video_id_from_url(url)
    if vid:
        return vid
    html = _get(url if "://" in url else "https://" + url)
    m = re.search(r'<link rel="canonical" href="https://www\.youtube\.com/watch\?v=([\w-]{11})"', html) \
        or re.search(r'"videoId":"([\w-]{11})"', html)
    if not m:
        raise RuntimeError(f"não achei uma live em {url}")
    return m.group(1)


def initial_continuation(html: str) -> tuple[str, str, str]:
    """Da página /live_chat tira (api_key, client_version, continuation)."""
    key = re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', html)
    ver = re.search(r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"', html) \
        or re.search(r'"clientVersion":"([^"]+)"', html)
    cont = re.search(
        r'"(?:invalidation|timed|reload)ContinuationData":\{[^{}]*?"continuation":"([^"]+)"', html
    ) or re.search(r'"continuation":"([^"]+)"', html)
    if not (key and cont):
        raise RuntimeError("chat indisponível (a live terminou ou o chat está desligado?)")
    return key.group(1), (ver.group(1) if ver else "2.20241101.00.00"), cont.group(1)


def _runs_text(message: dict) -> str:
    out = []
    for run in message.get("runs", []):
        if "text" in run:
            out.append(run["text"])
        elif "emoji" in run:
            em = run["emoji"]
            # emoji padrão vem com o caractere; emotes do canal vêm como :nome:
            if not em.get("isCustomEmoji") and em.get("emojiId") and len(em["emojiId"]) <= 8:
                out.append(em["emojiId"])
            else:
                sc = em.get("shortcuts") or [""]
                out.append(" " + sc[0].strip(":") + " ")
    return "".join(out).strip()


def parse_actions(data: dict) -> tuple[list[ChatMessage], str | None, float]:
    """Lê uma resposta do get_live_chat.

    Retorna (mensagens, próxima continuation, espera em segundos).
    """
    lcc: dict[str, Any] = data.get("continuationContents", {}).get("liveChatContinuation", {})
    msgs: list[ChatMessage] = []
    for action in lcc.get("actions", []):
        item = action.get("addChatItemAction", {}).get("item", {})
        r = item.get("liveChatTextMessageRenderer") or item.get("liveChatPaidMessageRenderer")
        if not r:
            continue
        text = _runs_text(r.get("message", {}))
        user = r.get("authorName", {}).get("simpleText", "?")
        icons = {
            b.get("liveChatAuthorBadgeRenderer", {}).get("icon", {}).get("iconType")
            for b in r.get("authorBadges", [])
        }
        is_mod = bool(icons & {"MODERATOR", "OWNER"})
        try:
            ts = int(r["timestampUsec"]) / 1e6
        except (KeyError, ValueError):
            ts = time.time()
        msgs.append(ChatMessage(user, text, ts, is_mod))

    nxt, wait = None, 1.0
    for c in lcc.get("continuations", []):
        for kind in ("invalidationContinuationData", "timedContinuationData",
                     "reloadContinuationData"):
            if kind in c:
                nxt = c[kind].get("continuation")
                wait = int(c[kind].get("timeoutMs", 1000)) / 1000
                break
        if nxt:
            break
    return msgs, nxt, min(max(wait, 0.5), 5.0)


def read_youtube_chat(url: str) -> Iterator[ChatMessage]:
    """Gera mensagens da live para sempre, reconectando se cair."""
    vid = resolve_video_id(url)
    backoff = 2
    while True:
        try:
            html = _get(f"https://www.youtube.com/live_chat?is_popout=1&v={vid}")
            key, ver, cont = initial_continuation(html)
            api = f"https://www.youtube.com/youtubei/v1/live_chat/get_live_chat?key={key}"
            ctx = {"client": {"clientName": "WEB", "clientVersion": ver, "hl": "pt"}}
            log.info("conectado ao chat do YouTube (%s)", vid)
            backoff = 2
            while cont:
                data = _post_json(api, {"context": ctx, "continuation": cont})
                msgs, cont, wait = parse_actions(data)
                yield from msgs
                time.sleep(wait)
            log.warning("chat do YouTube encerrou (a live acabou?)")
        except (OSError, ValueError, RuntimeError) as e:
            log.warning("chat do YouTube: %s — tentando de novo em %ss", e, backoff)
        time.sleep(backoff)
        backoff = min(backoff * 2, 60)
