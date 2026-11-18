"""Detecta momentos de "hype" a partir da atividade do chat."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, deque
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
    if not text.startswith("!"):  # "!comando" de bot não conta
        bonus += min(text.count("!"), 3) * 0.75  # exclamação: CORRE!!!
    if re.search(r"([^\Wk])\1{3,}", text.lower()):
        bonus += 1.0  # letra esticada: NAAAAAO, GOOOOL
    return 1.0 + bonus


def normalize(text: str) -> str:
    """Deixa parecidas iguais: 'NÃAAAO!!' e 'nao' viram 'nao'."""
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = " ".join(_WORD.findall(t))
    return re.sub(r"(.)\1+", r"\1", t)[:40]


# Tipo de cena -> (palavras/prefixos no chat, título do clipe)
CATEGORIES: dict[str, tuple[tuple[str, ...], str]] = {
    "engracado": (("kkk", "kekw", "lul", "omegalul", "lmao", "hahaha", "rsrs", "risada",
                   "morri", "chorando", "socorro"), "KKKKKKKKK"),
    "assalto": (("assalt", "roub", "banco", "joalheria", "cofre", "refem", "refém"),
                "O ASSALTO"),
    "tenso": (("morreu", "morre", "preso", "prenderam", "cadeia", "fuga", "foge",
               "persegui", "policia", "polícia", "viatura", "tiro", "matou", "wasted",
               "busted", "rip", "monkas", "tenso", "nãoo", "naoo", "plot", "missao",
               "missão", "final", "boss", "chefe", "traiu", "traição"), "CENA TENSA"),
    "meme": (("cinema", "aura", "goat", "lenda", "absurdo", "insano", "w", "l", "f",
              "ratio", "sus", "bait", "classico", "clássico", "pog", "pogchamp"),
             "CINEMA PURO"),
}
DEFAULT_TITLE = "OLHA ISSO"


def categorize(texts: list[str]) -> str:
    """Escolhe o tipo de cena que mais aparece nas mensagens (ou '' se nenhum)."""
    votes = Counter()
    for t in texts:
        words = _WORD.findall(t.lower())
        for cat, (keys, _) in CATEGORIES.items():
            if any(w == k or (len(k) > 2 and w.startswith(k)) for w in words for k in keys):
                votes[cat] += 1
    if not votes:
        return ""
    cat, n = votes.most_common(1)[0]
    return cat if n >= max(2, len(texts) * 0.15) else ""


HOOKS = {
    "engracado": ["{n} NÃO AGUENTOU KKKKK", "O CHAT INTEIRO CHOROU DE RIR",
                  "{n} NÃO ESPERAVA ISSO KKKK", "ISSO FOI DEMAIS KKKKKK"],
    "assalto": ["O ASSALTO DO {n} DEU RUIM?", "{n} TENTOU O ASSALTO MAIS ARRISCADO",
                "ESPERA O FINAL DESSE ASSALTO", "ELES IAM ROUBAR TUDO..."],
    "tenso": ["ESPERA O FINAL...", "NINGUÉM ESPERAVA ISSO", "DEU MUITO RUIM PRO {n}",
              "{n} NÃO VIU ISSO VINDO"],
    "meme": ["ISSO É CINEMA PURO", "A AURA DO {n} É OUTRA", "JOGADA DE GÊNIO DO {n}",
             "O CHAT FICOU MALUCO"],
    "": ["OLHA O QUE O {n} FEZ", "ESPERA ATÉ O FINAL", "{n} PERDEU A CABEÇA",
         "VOCÊ NÃO VAI ACREDITAR NISSO"],
}


def hook(category: str, name: str = "") -> str:
    """Legenda-gancho para o topo do clipe."""
    import random
    opts = HOOKS.get(category) or HOOKS[""]
    if not name:
        opts = [o for o in opts if "{n}" not in o] or ["ESPERA ATÉ O FINAL"]
    return random.choice(opts).replace("{n}", name.upper())


def title_for(category: str, name: str = "") -> str:
    return hook(category, name)


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
        self._recent: deque[tuple[float, str]] = deque()
        self._counts: Counter[str] = Counter()
        self._texts: deque[tuple[float, str]] = deque(maxlen=400)

    def add(self, ts: float, text: str) -> float | None:
        """Registra uma mensagem; retorna o horário do pico se disparou."""
        if self._started is None:
            self._started = ts
        score = message_score(text, self.keywords)
        self._texts.append((ts, text))
        # repetição: a mesma coisa (ou parecida) sendo dita por muita gente
        while self._recent and self._recent[0][0] < ts - self.window:
            _, old = self._recent.popleft()
            self._counts[old] -= 1
        key = normalize(text)
        if key:
            score += min(self._counts[key], 8) * 1.0
            self._recent.append((ts, key))
            self._counts[key] += 1
        self._events.append((ts, score))
        return self.tick(ts)

    def category(self, now: float, span: float = 20.0) -> str:
        """Tipo de cena do momento, olhando o chat dos últimos ``span`` s."""
        return categorize([t for ts, t in self._texts if ts >= now - span])

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


@dataclass
class LoudnessDetector:
    """Pico de áudio: grito, risada alta, explosão, tiroteio.

    Recebe o volume médio (dB) de cada trecho e dispara quando fica
    ``jump_db`` acima da média recente.
    """

    jump_db: float = 9.0
    warmup: float = 60.0
    alpha: float = 0.05

    def __post_init__(self) -> None:
        self._baseline: float | None = None
        self._started: float | None = None

    def add(self, ts: float, mean_db: float) -> bool:
        if mean_db <= -80:  # silêncio total / sem áudio
            return False
        if self._started is None:
            self._started = ts
        if self._baseline is None:
            self._baseline = mean_db
            return False
        fired = ts - self._started >= self.warmup and mean_db >= self._baseline + self.jump_db
        self._baseline += self.alpha * (mean_db - self._baseline)
        return fired
