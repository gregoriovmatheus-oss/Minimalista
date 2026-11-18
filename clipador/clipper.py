"""Junta os segmentos do buffer em um clipe .mp4."""

from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from .recorder import Recorder

log = logging.getLogger(__name__)


def _slug(text: str) -> str:
    return re.sub(r"[^\w-]+", "-", text, flags=re.UNICODE).strip("-")[:40] or "clipe"


class Clipper:
    def __init__(
        self,
        recorder: Recorder,
        out_dir: Path,
        pre_seconds: float = 30,
        post_seconds: float = 10,
    ) -> None:
        self.recorder = recorder
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.pre = pre_seconds
        self.post = post_seconds

    def clip_async(self, moment: float, reason: str = "manual") -> threading.Thread:
        """Agenda um clipe ao redor de ``moment`` sem travar o chat."""
        t = threading.Thread(target=self.clip, args=(moment, reason), daemon=True)
        t.start()
        return t

    def clip(self, moment: float, reason: str = "manual") -> Path | None:
        start, end = moment - self.pre, moment + self.post
        # espera o "depois" ser gravado
        deadline = end + 30
        while self.recorder.latest_time() < end and time.time() < deadline:
            if not self.recorder.running and self.recorder.latest_time() < end:
                break
            time.sleep(0.5)

        segs = self.recorder.segments_between(start, end)
        segs = [s for s in segs if s.path.exists()]
        if not segs:
            log.error("nenhum segmento no buffer para %s", reason)
            return None

        stamp = datetime.fromtimestamp(moment).strftime("%Y%m%d-%H%M%S")
        out = self.out_dir / f"{stamp}_{_slug(reason)}.mp4"
        lst = out.with_suffix(".txt")
        lst.write_text("".join(f"file '{s.path.resolve()}'\n" for s in segs))
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(lst),
            "-c", "copy", "-bsf:a", "aac_adtstoasc",
            "-movflags", "+faststart", str(out),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            # áudio que não é AAC não aceita o filtro: tenta sem ele
            cmd.remove("-bsf:a")
            cmd.remove("aac_adtstoasc")
            res = subprocess.run(cmd, capture_output=True, text=True)
        lst.unlink(missing_ok=True)
        if res.returncode != 0:
            log.error("ffmpeg falhou: %s", res.stderr.strip())
            return None
        dur = segs[-1].end - segs[0].start
        log.info("✂  clipe salvo: %s (%.0fs, %s)", out.name, dur, reason)
        return out
