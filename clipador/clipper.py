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
        self.cooldown = 45.0
        self._last_auto = float("-inf")
        self._auto_lock = threading.Lock()

    def auto_clip(self, moment: float, reason: str, title: str) -> bool:
        """Clipe automático (chat ou áudio), sem repetir o mesmo momento."""
        with self._auto_lock:
            if moment - self._last_auto < self.cooldown:
                return False
            self._last_auto = moment
        threading.Thread(target=self.clip, args=(moment, reason, title), daemon=True).start()
        return True

    def clip_async(self, moment: float, reason: str = "manual") -> threading.Thread:
        """Agenda um clipe ao redor de ``moment`` sem travar o chat."""
        t = threading.Thread(target=self.clip, args=(moment, reason), daemon=True)
        t.start()
        return t

    def clip(self, moment: float, reason: str = "manual", title: str = "") -> Path | None:
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
            if not title:
                title = reason if reason != "manual" and not reason.startswith("chat-") \
                    else "OLHA ISSO"
            make_vertical(out, out.with_name(out.stem + "_vertical.mp4"), title,
                          f"@{self.label}" if self.label else "")
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


def _face_boxes(src: Path, samples: int = 8):
    """Rostos encontrados em ``samples`` quadros do clipe: [(quadro_w, quadro_h, [(x,y,w,h)])]."""
    import cv2  # opcional

    cap = cv2.VideoCapture(str(src))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 300
    casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    out = []
    for i in range(samples):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * (i + 0.5) / samples))
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        fh, fw = gray.shape
        faces = casc.detectMultiScale(gray, 1.1, 6, minSize=(max(24, fh // 30),) * 2)
        out.append((fw, fh, [tuple(map(int, f)) for f in faces]))
    cap.release()
    return out


def find_facecam(src: Path) -> tuple[int, int, int, int] | None:
    """Acha a câmera do streamer: o rosto que fica PARADO no mesmo lugar na
    maioria dos quadros (rostos do jogo se mexem). Retorna o recorte 4:3."""
    try:
        frames = _face_boxes(src)
    except Exception as e:  # sem opencv ou vídeo ilegível
        log.debug("detecção de câmera indisponível: %s", e)
        return None
    if not frames:
        return None
    fw, fh = frames[0][0], frames[0][1]
    clusters: list[list[tuple[int, int, int, int]]] = []
    for _, _, faces in frames:
        for f in faces:
            cx, cy = f[0] + f[2] / 2, f[1] + f[3] / 2
            for c in clusters:
                g = c[0]
                if abs(cx - (g[0] + g[2] / 2)) < g[2] * 0.6 and abs(cy - (g[1] + g[3] / 2)) < g[3] * 0.6:
                    c.append(f)
                    break
            else:
                clusters.append([f])
    good = [c for c in clusters if len(c) >= max(3, len(frames) // 2)]
    if not good:
        return None
    best = max(good, key=len)
    x = sorted(b[0] for b in best)[len(best) // 2]
    y = sorted(b[1] for b in best)[len(best) // 2]
    w = sorted(b[2] for b in best)[len(best) // 2]
    # recorte 4:3 ao redor do rosto (rosto ~1/3 da largura, um pouco acima do meio)
    cw = min(fw, int(w * 3.2)) // 2 * 2
    ch = min(fh, int(cw * 3 / 4)) // 2 * 2
    cw = min(cw, int(ch * 4 / 3)) // 2 * 2
    cx, cy = x + w / 2, y + w / 2
    x0 = int(min(max(cx - cw / 2, 0), fw - cw))
    y0 = int(min(max(cy - ch * 0.45, 0), fh - ch))
    return x0, y0, cw, ch


def make_vertical(src: Path, out: Path, title: str = "", footer: str = "") -> Path | None:
    """9:16 (1080x1920) para TikTok/Shorts/Reels: vídeo no centro, fundo desfocado,
    título em cima."""
    bg = ("[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
          "boxblur=20:2,eq=brightness=-0.15[bg];")
    cam = find_facecam(src)
    if cam:
        # câmera do streamer em cima, jogo inteiro embaixo
        x, y, w, h = cam
        vf = ("[0:v]split=3[a][b][c];" + bg +
              f"[b]crop={w}:{h}:{x}:{y},scale=1080:810[cam];"
              "[c]scale=1080:-2[game];"
              "[bg][cam]overlay=0:230[t];[t][game]overlay=0:1080")
        title_y, footer_y = "70", "1735"
        log.info("📷 câmera do streamer encontrada em x=%d y=%d", x, y)
    else:
        # sem câmera: jogo inteiro (sem cortar os cantos) no meio
        vf = ("[0:v]split[a][b];" + bg +
              "[b]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
        title_y, footer_y = "h*0.13", "h*0.80"
    txts: list[Path] = []
    font = _font()
    if font:
        f = font.replace("\\", "/").replace(":", "\\:")
        for i, (text, size, y) in enumerate(((title, 92, title_y), (footer, 54, footer_y))):
            if not text:
                continue
            txt = out.with_suffix(f".t{i}.txt")
            txt.write_text(text[:40])
            txts.append(txt)
            t = str(txt.resolve()).replace("\\", "/").replace(":", "\\:")
            vf += (f",drawtext=fontfile='{f}':textfile='{t}':fontsize={size}:fontcolor=white:"
                   f"borderw=6:bordercolor=black:x=(w-tw)/2:y={y}")
    vf += "[v]"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
           "-filter_complex", vf, "-map", "[v]", "-map", "0:a?",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
           "-r", "30", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
           "-f", "mp4", str(out) + ".part"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        Path(str(out) + ".part").replace(out)  # só aparece quando está completo
    for txt in txts:
        txt.unlink(missing_ok=True)
    if res.returncode != 0:
        log.error("versão vertical falhou: %s", res.stderr.strip()[-300:])
        return None
    log.info("📱 pronto para postar: %s", out.name)
    return out
