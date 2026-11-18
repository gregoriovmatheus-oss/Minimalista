"""Leitura anônima do chat da Twitch via IRC (não precisa de login)."""

from __future__ import annotations

import logging
import random
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Iterator

log = logging.getLogger(__name__)

HOST = "irc.chat.twitch.tv"
PORT = 6697


@dataclass
class ChatMessage:
    user: str
    text: str
    ts: float
    is_mod: bool = False


def parse_privmsg(raw: str, ts: float | None = None) -> ChatMessage | None:
    """Converte uma linha IRC em ChatMessage (ou None se não for mensagem)."""
    tags: dict[str, str] = {}
    line = raw
    if line.startswith("@"):
        tag_str, _, line = line.partition(" ")
        for kv in tag_str[1:].split(";"):
            k, _, v = kv.partition("=")
            tags[k] = v
    if " PRIVMSG " not in line:
        return None
    prefix, _, rest = line.partition(" PRIVMSG ")
    _, _, text = rest.partition(" :")
    user = tags.get("display-name") or prefix.lstrip(":").split("!")[0]
    badges = tags.get("badges", "")
    is_mod = tags.get("mod") == "1" or "broadcaster/" in badges
    return ChatMessage(user, text.strip(), ts or time.time(), is_mod)


def read_chat(channel: str) -> Iterator[ChatMessage]:
    """Gera mensagens do chat para sempre, reconectando se cair."""
    channel = channel.lower().lstrip("#")
    backoff = 1
    while True:
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((HOST, PORT), timeout=360) as raw_sock:
                with ctx.wrap_socket(raw_sock, server_hostname=HOST) as sock:
                    nick = f"justinfan{random.randint(10000, 99999)}"
                    sock.sendall(b"CAP REQ :twitch.tv/tags\r\n")
                    sock.sendall(f"NICK {nick}\r\n".encode())
                    sock.sendall(f"JOIN #{channel}\r\n".encode())
                    log.info("conectado ao chat de #%s", channel)
                    backoff = 1
                    buf = b""
                    while True:
                        data = sock.recv(4096)
                        if not data:
                            raise ConnectionError("chat desconectou")
                        buf += data
                        *lines, buf = buf.split(b"\r\n")
                        for bline in lines:
                            line = bline.decode("utf-8", "replace")
                            if line.startswith("PING"):
                                sock.sendall(b"PONG :tmi.twitch.tv\r\n")
                                continue
                            msg = parse_privmsg(line)
                            if msg:
                                yield msg
        except (OSError, ConnectionError) as e:
            log.warning("chat: %s — reconectando em %ss", e, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
