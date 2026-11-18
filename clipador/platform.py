"""Descobre se o alvo é Twitch ou YouTube e monta a URL para o streamlink."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator
from urllib.parse import urlparse

from .chat import ChatMessage, read_chat
from .youtube_chat import read_youtube_chat


@dataclass
class Target:
    platform: str  # "twitch" | "youtube" | "kick"
    stream_url: str
    name: str  # usado em logs e nome de pasta

    def chat(self) -> Iterator[ChatMessage]:
        if self.platform == "kick":  # sem chat: corta por áudio + curadoria
            return _no_chat()
        reader: Callable[[str], Iterator[ChatMessage]] = (
            read_chat if self.platform == "twitch" else read_youtube_chat
        )
        return reader(self.name if self.platform == "twitch" else self.stream_url)


def _no_chat() -> Iterator[ChatMessage]:
    import time
    while True:
        time.sleep(3600)
        yield from ()


def resolve(alvo: str) -> Target:
    """Aceita: 'gaules', twitch.tv/gaules, youtube.com/watch?v=..., youtu.be/...,
    youtube.com/@canal/live ou youtube.com/live/ID."""
    s = alvo.strip()
    u = urlparse(s if "://" in s else "https://" + s)
    host = (u.hostname or "").lower()
    if "youtube.com" in host or "youtu.be" in host:
        url = s if "://" in s else "https://" + s
        return Target("youtube", url, u.path.strip("/").replace("/", "_") or "youtube")
    if "kick.com" in host:
        canal = u.path.strip("/").split("/")[0].lower()
        return Target("kick", f"https://kick.com/{canal}", canal)
    if "twitch.tv" in host:
        canal = u.path.strip("/").split("/")[0]
    elif "." not in s and "/" not in s:
        canal = s.lstrip("#@")
    else:
        raise ValueError(f"não reconheci '{alvo}': use um canal da Twitch ou link do YouTube")
    canal = canal.lower()
    return Target("twitch", f"https://www.twitch.tv/{canal}", canal)
