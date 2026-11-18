"""Grava a live em segmentos curtos e mantém um buffer circular em disco."""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class Segment:
    path: Path
    start: float  # horário (epoch) em que o trecho começou
    end: float  # horário (epoch) em que o trecho terminou

    @property
    def duration(self) -> float:
        return self.end - self.start


class Recorder:
    """Puxa o stream (streamlink ou qualquer entrada do ffmpeg) e o fatia em .ts.

    Cada segmento concluído entra na lista com seu horário real; os mais antigos
    que ``buffer_seconds`` são apagados.
    """

    def __init__(
        self,
        buffer_dir: Path,
        stream_url: str | None = None,
        quality: str = "best",
        source: str | None = None,
        segment_seconds: int = 2,
        buffer_seconds: int = 180,
        realtime_input: bool = False,
    ) -> None:
        if not stream_url and not source:
            raise ValueError("informe a URL da live ou uma fonte de teste")
        self.buffer_dir = Path(buffer_dir)
        self.stream_url = stream_url
        self.quality = quality
        self.source = source
        self.segment_seconds = segment_seconds
        self.buffer_seconds = buffer_seconds
        self.realtime_input = realtime_input
        self.segments: list[Segment] = []
        self._lock = threading.Lock()
        self._procs: list[subprocess.Popen] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ início
    def start(self) -> None:
        if self.buffer_dir.exists():
            shutil.rmtree(self.buffer_dir)
        self.buffer_dir.mkdir(parents=True)
        self._attempt = 0
        self._new_dir()
        self._spawn()
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    def _new_dir(self) -> None:
        self._attempt += 1
        self._dir = self.buffer_dir / f"r{self._attempt:03d}"
        self._dir.mkdir()

    def _ffmpeg_cmd(self, input_arg: str) -> list[str]:
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
        if self.realtime_input:
            cmd.append("-re")
        cmd += [
            "-i", input_arg,
            "-map", "0:v:0?", "-map", "0:a:0?",
            "-c", "copy",
            "-f", "segment",
            "-segment_time", str(self.segment_seconds),
            "-segment_format", "mpegts",
            "-segment_list", str(self._dir / "lista.csv"),
            "-segment_list_type", "csv",
            "-reset_timestamps", "1",
            str(self._dir / "seg_%07d.ts"),
        ]
        return cmd

    def _spawn(self) -> None:
        if self.source:
            ff = subprocess.Popen(self._ffmpeg_cmd(self.source), stdin=subprocess.DEVNULL)
            self._procs = [ff]
            return
        sl = subprocess.Popen(
            [
                "streamlink", "--stdout", "--loglevel", "warning",
                "--retry-streams", "5", "--retry-max", "12",
                self.stream_url, self.quality,
            ],
            stdout=subprocess.PIPE,
        )
        ff = subprocess.Popen(self._ffmpeg_cmd("pipe:0"), stdin=sl.stdout)
        assert sl.stdout is not None
        sl.stdout.close()  # o ffmpeg é o único leitor
        self._procs = [sl, ff]

    # ------------------------------------------------------------- vigilância
    def _watch(self) -> None:
        csv_path = self._dir / "lista.csv"
        lines_read = 0
        while not self._stop.is_set():
            if (not self.source and self._procs and self._procs[-1].poll() is not None):
                # live caiu: tenta de novo a cada minuto (o streamer pode voltar)
                log.warning("live offline ou caiu — tentando de novo em 60s")
                if self._stop.wait(60):
                    break
                self._new_dir()
                self._spawn()
                csv_path, lines_read = self._dir / "lista.csv", 0
                continue
            if csv_path.exists():
                lines = csv_path.read_text().splitlines()
                now = time.time()
                for line in lines[lines_read:]:
                    self._add_from_csv(line, now)
                lines_read = len(lines)
            self._prune()
            if self._procs and self._procs[-1].poll() is not None:
                log.warning("gravação terminou (live caiu ou fonte acabou)")
                break
            self._stop.wait(0.5)

    def _add_from_csv(self, line: str, finished_at: float) -> None:
        # formato: nome,inicio,fim  (tempos relativos ao stream)
        try:
            name, t0, t1 = line.rsplit(",", 2)
            dur = float(t1) - float(t0)
        except ValueError:
            return
        seg = Segment(self._dir / name, finished_at - dur, finished_at)
        with self._lock:
            self.segments.append(seg)
        log.debug("segmento %s (%.1fs)", name, dur)

    def _prune(self) -> None:
        limit = time.time() - self.buffer_seconds
        with self._lock:
            old = [s for s in self.segments if s.end < limit]
            self.segments = [s for s in self.segments if s.end >= limit]
        for s in old:
            s.path.unlink(missing_ok=True)

    # ---------------------------------------------------------------- consulta
    def segments_between(self, start: float, end: float, slack: float = 0.25) -> list[Segment]:
        """Segmentos que cobrem [start, end]; ignora os que só encostam na borda."""
        with self._lock:
            return [s for s in self.segments
                    if s.end > start + slack and s.start < end - slack]

    def latest_time(self) -> float:
        with self._lock:
            return self.segments[-1].end if self.segments else 0.0

    def segments_after(self, t: float) -> list[Segment]:
        with self._lock:
            return [s for s in self.segments if s.end > t]

    @property
    def running(self) -> bool:
        return bool(self._procs) and self._procs[-1].poll() is None

    def stop(self) -> None:
        self._stop.set()
        for p in reversed(self._procs):
            if p.poll() is None:
                p.terminate()
        for p in self._procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        if self._thread:
            self._thread.join(timeout=2)


def mean_volume(path: Path) -> float:
    """Volume médio do trecho em dB (-91 se não tiver áudio)."""
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0?",
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    for line in r.stderr.splitlines():
        if "mean_volume:" in line:
            try:
                return float(line.split("mean_volume:")[1].split()[0])
            except ValueError:
                pass
    return -91.0
