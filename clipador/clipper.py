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

from .detector import hook
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
        self.signature = "@viceclips.vibr"
        self.cooldown = 45.0
        self._last_auto = float("-inf")
        self._auto_lock = threading.Lock()
        self._cands: list = []

    def auto_clip(self, moment: float, reason: str, title: str,
                  score: float = 1.0, source: str = "chat") -> bool:
        """Registra um candidato; a curadoria escolhe o melhor de cada janela."""
        with self._auto_lock:
            self._cands.append((moment, score, reason, title, source))
        return True

    def start_curator(self, window: float = 240, min_score: float = 2.0) -> None:
        self._cands: list = getattr(self, "_cands", [])
        threading.Thread(target=self._curate, args=(window, min_score), daemon=True).start()

    def _curate(self, window: float, min_score: float) -> None:
        cats = ("engracado", "assalto", "tenso", "meme")
        while True:
            time.sleep(window)
            with self._auto_lock:
                cands, self._cands = self._cands, []
            if not cands:
                continue
            audio = [c for c in cands if c[4] == "audio"]
            best, best_score = None, 0.0
            for c in cands:
                sc = c[1] + (0.5 if c[2] in cats else 0)
                if c[4] != "audio":  # chat + áudio juntos = momento forte
                    near = [a for a in audio if -20 <= c[0] - a[0] <= 5]
                    if near:
                        sc += 1.0 + max(a[1] for a in near) * 0.5
                if sc > best_score:
                    best, best_score = c, sc
            if best and best_score >= min_score:
                moment, _, reason, title, source = best
                # chat reage ~10s depois do acontecimento; áudio é na hora
                pre, post = (18, 10) if source == "audio" else (25, 5)
                log.info("🏆 [%s] melhor momento da janela: %s (nota %.1f)",
                         self.label, reason, best_score)
                threading.Thread(target=self.clip, args=(moment, reason, title, pre, post),
                                 daemon=True).start()
            else:
                log.info("· [%s] nada forte o bastante nesta janela (melhor %.1f)",
                         self.label, best_score)

    def clip_async(self, moment: float, reason: str = "manual") -> threading.Thread:
        """Agenda um clipe ao redor de ``moment`` sem travar o chat."""
        t = threading.Thread(target=self.clip, args=(moment, reason), daemon=True)
        t.start()
        return t

    def clip(self, moment: float, reason: str = "manual", title: str = "",
             pre: float | None = None, post: float | None = None) -> Path | None:
        if reason != "manual":
            self._last_auto = moment
        start = moment - (self.pre if pre is None else pre)
        end = moment + (self.post if post is None else post)
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
                    else hook("", self.label)
            vert = out.with_name(out.stem + "_vertical.mp4")
            words = []
            try:
                from .legenda import transcribe, transcript_text
                words = transcribe(out)
                vert.with_suffix(".txt").write_text(
                    f"{self.label} | {reason} | {transcript_text(words)}\n")
            except Exception as e:  # legenda é bônus: nunca derruba o clipe
                log.warning("transcrição falhou: %s", e)
            make_vertical(out, vert, title, self.signature, words)
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


_ENCODE = threading.Semaphore(3)


def _wrap(text: str, width: int) -> list[str]:
    lines, cur = [], ""
    for w in text.split():
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    return lines + ([cur] if cur else [])


def make_vertical(src: Path, out: Path, title: str = "", footer: str = "",
                  words: list | None = None) -> Path | None:
    """9:16 (1080x1920) para TikTok/Shorts/Reels: vídeo no centro, fundo desfocado,
    título em cima."""
    bg = ("[a]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,"
          "boxblur=20:2,eq=brightness=-0.15[bg];")
    cam = find_facecam(src)
    if cam:
        # câmera do streamer em cima, jogo inteiro embaixo
        x, y, w, h = cam
        vf = ("[0:v]split=3[a][b][c];" + bg +
              f"[b]crop={w}:{h}:{x}:{y},scale=720:540[cam];"
              "[c]scale=720:-2[game];"
              "[bg][cam]overlay=0:153[t];[t][game]overlay=0:720")
        title_y, footer_y = "27", "1157"
        sub_margin = 520  # entre a câmera e o jogo
        log.info("📷 câmera do streamer encontrada em x=%d y=%d", x, y)
    else:
        # sem câmera: jogo inteiro (sem cortar os cantos) no meio
        vf = ("[0:v]split[a][b];" + bg +
              "[b]scale=720:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
        title_y, footer_y = "h*0.11", "h*0.80"
        sub_margin = 400  # logo abaixo do jogo
    txts: list[Path] = []
    font = _font()
    if font:
        f = font.replace("\\", "/").replace(":", "\\:")
        # gancho em até 2 linhas, cada uma numa tarja vermelha; assinatura embaixo
        lines = _wrap(title.upper(), 18)[:2] if title else []
        items = [(ln, 52, f"({title_y})+{i * 74}", True) for i, ln in enumerate(lines)]
        if footer:
            items.append((footer, 36, footer_y, False))
        for i, (text, size, y, box) in enumerate(items):
            txt = out.with_suffix(f".t{i}.txt")
            txt.write_text(text)
            txts.append(txt)
            t = str(txt.resolve()).replace("\\", "/").replace(":", "\\:")
            style = ("box=1:boxcolor=0xE11D48@0.95:boxborderw=12:borderw=3:bordercolor=black"
                     if box else "borderw=5:bordercolor=black")
            vf += (f",drawtext=fontfile='{f}':textfile='{t}':fontsize={size}:fontcolor=white:"
                   f"{style}:x=(w-tw)/2:y={y}")
    if words:
        from .legenda import write_ass
        ass = write_ass(words, out.with_suffix(".ass"), sub_margin)
        if ass:
            txts.append(ass)
            vf += ",subtitles='" + str(ass.resolve()).replace(":", "\\:") + "'"
    vf += "[v]"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
           "-filter_complex", vf, "-map", "[v]", "-map", "0:a?",
           "-c:v", "libx264", "-preset", "superfast", "-crf", "23", "-pix_fmt", "yuv420p",
           "-r", "30", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
           "-f", "mp4", str(out) + ".part"]
    with _ENCODE:  # fila: no máximo 2 edições ao mesmo tempo
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
