"""Transcrição (faster-whisper) e legenda estilo TikTok (.ass) para os clipes."""

from __future__ import annotations

import logging
import re
import subprocess
import threading
from pathlib import Path

log = logging.getLogger(__name__)
_model = None
_lock = threading.Lock()

PALAVROES = {
    "porra": "P*RRA", "caralho": "C*RALHO", "merda": "M*RDA", "puta": "P*TA",
    "foda": "F*DA", "fodase": "F*DA-SE", "fudido": "F*DIDO", "buceta": "B*CETA",
    "cacete": "C*CETE", "arrombado": "ARR*MBADO",
}


def _audio(path: Path):
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-ac", "1",
                          "-ar", "16000", "-f", "f32le", "-"], capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def transcribe(path: Path) -> list[tuple[float, float, str]]:
    """Palavras com tempo [(início, fim, palavra)]; [] se não houver fala ou modelo."""
    global _model
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return []
    with _lock:  # um modelo só, uma transcrição por vez
        if _model is None:
            _model = WhisperModel("small", device="cpu", compute_type="int8")
        segs, _ = _model.transcribe(_audio(path), language="pt", word_timestamps=True,
                                    vad_filter=True, beam_size=1)
        return [(w.start, w.end, w.word.strip()) for s in segs for w in (s.words or [])]


def censura(t: str) -> str:
    def rep(m):
        return PALAVROES.get(m.group(0).lower(), m.group(0))
    return re.sub(r"\w+", rep, t)


def _ts(t: float) -> str:
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def write_ass(words: list[tuple[float, float, str]], out: Path, margin_v: int) -> Path | None:
    """Legenda amarela grande, 3 palavras por vez, no ritmo da fala."""
    if not words:
        return None
    ev, i = [], 0
    while i < len(words):
        ch = words[i:i + 3]
        i += 3
        txt = censura(" ".join(w[2] for w in ch)).upper().strip(" ,.?!")
        if not txt:
            continue
        end = max(ch[-1][1], ch[0][0] + 0.4)
        if i < len(words):
            end = min(end + 0.15, words[i][0])
        ev.append(f"Dialogue: 0,{_ts(ch[0][0])},{_ts(end)},L,,0,0,0,,{txt}")
    out.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 720\nPlayResY: 1280\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, "
        "Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, "
        "Encoding\n"
        f"Style: L,DejaVu Sans,60,&H0000FFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,"
        f"0,0,1,6,2,2,30,30,{margin_v},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        + "\n".join(ev) + "\n")
    return out


def transcript_text(words: list[tuple[float, float, str]]) -> str:
    return censura(" ".join(w[2] for w in words))
