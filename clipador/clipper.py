"""Junta os segmentos do buffer em um clipe .mp4."""

from __future__ import annotations

import logging
import re
import shutil
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
        vertical: bool = True,
        label: str = "",
    ) -> None:
        self.recorder = recorder
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.pre = pre_seconds
        self.post = post_seconds
        self.vertical = vertical
        self.label = label

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
        if self.vertical:
            title = reason if reason not in ("manual", "hype") and not reason.startswith("chat-") \
                else self.label
            make_vertical(out, out.with_name(out.stem + "_vertical.mp4"), title)
        return out


def _font() -> str | None:
    if shutil.which("fc-match"):
        r = subprocess.run(["fc-match", "-f", "%{file}", "sans:bold"],
                           capture_output=True, text=True)
        if r.returncode == 0 and Path(r.stdout).exists():
            return r.stdout
    for f in ("C:/Windows/Fonts/arialbd.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
              "/Library/Fonts/Arial Bold.ttf"):
        if Path(f).exists():
            return f
    return None


def make_vertical(src: Path, out: Path, title: str = "") -> Path | None:
    """9:16 (1080x1920) para TikTok/Shorts/Reels: vídeo no centro, fundo desfocado,
    título em cima."""
    vf = ("[0:v]split[a][b];"
          "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
          "boxblur=20:2,eq=brightness=-0.15[bg];"
          "[b]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
    txt = None
    font = _font()
    if title and font:
        txt = out.with_suffix(".titulo.txt")
        txt.write_text(title[:60])
        f = font.replace("\\", "/").replace(":", "\\:")
        t = str(txt.resolve()).replace("\\", "/").replace(":", "\\:")
        vf += (f",drawtext=fontfile='{f}':textfile='{t}':fontsize=72:fontcolor=white:"
               "borderw=5:bordercolor=black:x=(w-tw)/2:y=h*0.16")
    vf += "[v]"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
           "-filter_complex", vf, "-map", "[v]", "-map", "0:a?",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
           "-r", "30", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
           "-f", "mp4", str(out) + ".part"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        Path(str(out) + ".part").replace(out)  # só aparece quando está completo
    if txt:
        txt.unlink(missing_ok=True)
    if res.returncode != 0:
        log.error("versão vertical falhou: %s", res.stderr.strip()[-300:])
        return None
    log.info("📱 pronto para postar: %s", out.name)
    return out
