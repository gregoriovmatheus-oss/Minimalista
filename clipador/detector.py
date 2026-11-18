"""Detecta momentos de "hype" a partir da atividade do chat."""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field

DEFAULT_KEYWORDS = {
    # risada
    "kekw": 2.0, "lul": 1.5, "lmao": 1.5, "omegalul": 2.0, "kkkk": 4.0,
    "hahaha": 1.0, "rsrs": 0.5,
    # surpresa / hype
    "pog": 2.0, "pogchamp": 2.0, "poggers": 2.0, "pogu": 2.0, "monkas": 1.5,
    "wtf": 1.5, "omg": 1.5, "caralho": 1.5, "nossa": 1.0, "gg": 1.0,
    # pedido explícito
    "clip": 3.0, "clipa": 3.0, "clipe": 3.0, "clipou": 3.0,
}

# emojis (comuns no chat do YouTube); contam uma vez por mensagem
DEFAULT_EMOJIS: dict[str, float] = {}  # emojis não contam

_WORD = re.compile(r"[\w]+", re.UNICODE)


def message_score(
    text: str, keywords: dict[str, float], emojis: dict[str, float] = DEFAULT_EMOJIS
) -> float:
    """1 ponto por mensagem + bônus por palavras-chave e emojis (uma vez cada)."""
    words = {w.lower() for w in _WORD.findall(text)}
    bonus = sum(v for e, v in emojis.items() if e in text)
    for w in words:
        if w in keywords:
            bonus += keywords[w]
        elif w.startswith("k") and set(w) <= {"k"} and len(w) >= 4:
            bonus += keywords.get("kkkk", 0.0)  # kkkkkkkk de qualquer tamanho
    if text.isupper() and len(text) > 5:
        bonus += 0.5  # GRITANDO
    return 1.0 + bonus


@dataclass
class HypeDetector:
    """Compara a pontuação dos últimos ``window`` s com a média histórica.

    Dispara quando a janela recente for ``threshold`` vezes maior que a linha
    de base (média móvel exponencial) e acima de um mínimo absoluto.
    """

    window: float = 10.0
    threshold: float = 2.5
    min_score: float = 15.0
    cooldown: float = 45.0
    warmup: float = 60.0
    alpha: float = 0.02  # suavização da linha de base
    keywords: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_KEYWORDS))

    def __post_init__(self) -> None:
        self._events: deque[tuple[float, float]] = deque()
        self._baseline: float | None = None
        self._started: float | None = None
        self._last_fire = float("-inf")
        self._last_tick: float | None = None

    def add(self, ts: float, text: str) -> float | None:
        """Registra uma mensagem; retorna o horário do pico se disparou."""
        if self._started is None:
            self._started = ts
        self._events.append((ts, message_score(text, self.keywords)))
        return self.tick(ts)

    def current(self, now: float) -> float:
        while self._events and self._events[0][0] < now - self.window:
            self._events.popleft()
        return sum(s for _, s in self._events)

    @property
    def baseline(self) -> float:
        return self._baseline or 0.0

    def tick(self, now: float) -> float | None:
        """Atualiza a linha de base (chamar ~1x/s mesmo sem mensagens)."""
        if self._started is None:
            self._started = now
        score = self.current(now)
        # atualiza a média a cada segundo decorrido
        if self._last_tick is None or now - self._last_tick >= 1.0:
            self._last_tick = now
            if self._baseline is None:
                self._baseline = score
            else:
                self._baseline += self.alpha * (score - self._baseline)

        if now - self._started < self.warmup:
            return None
        if now - self._last_fire < self.cooldown:
            return None
        base = max(self.baseline, 1.0)
        if score >= self.min_score and score >= self.threshold * base:
            self._last_fire = now
            return now
        return None
