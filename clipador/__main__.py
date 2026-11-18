"""Linha de comando: python -m clipador <canal-da-twitch | link-da-live>"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from pathlib import Path

from .clipper import Clipper
from .detector import HypeDetector, LoudnessDetector, title_for
from .platform import Target, resolve
from .recorder import Recorder, mean_volume

log = logging.getLogger("clipador")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="clipador",
        description="Acompanha uma live da Twitch ou do YouTube e corta clipes ao vivo.",
    )
    p.add_argument("lives", nargs="*", metavar="live",
                   help="um ou mais canais da Twitch (ex: gaules) ou links de live (Twitch/YouTube)")
    p.add_argument("-q", "--qualidade", default="best", help="qualidade do streamlink (padrão: best)")
    p.add_argument("-o", "--saida", default="clipes", type=Path, help="pasta dos clipes")
    p.add_argument("--antes", type=float, default=30, help="segundos antes do momento (padrão: 30)")
    p.add_argument("--depois", type=float, default=10, help="segundos depois do momento (padrão: 10)")
    p.add_argument("--buffer", type=int, default=180, help="segundos guardados em disco (padrão: 180)")
    p.add_argument("--sem-chat", action="store_true", help="desliga o corte automático pelo chat")
    p.add_argument("--sensibilidade", type=float, default=1.7,
                   help="quantas vezes acima do normal o chat precisa ficar (padrão: 1.7)")
    p.add_argument("--minimo", type=float, default=15, help="pontuação mínima na janela (padrão: 15)")
    p.add_argument("--janela", type=float, default=10, help="janela do chat em segundos (padrão: 10)")
    p.add_argument("--intervalo", type=float, default=45, help="tempo mínimo entre clipes automáticos")
    p.add_argument("--aquecimento", type=float, default=60,
                   help="segundos observando o chat antes de cortar (padrão: 60)")
    p.add_argument("--comando", default="!clip",
                   help="comando que mods/streamer usam no chat para cortar ('' desliga)")
    p.add_argument("--melhor-a-cada", type=float, default=6,
                   help="sem clipe por N minutos? corta o melhor momento do período (0 desliga)")
    p.add_argument("--sem-audio", action="store_true",
                   help="não corta por pico de volume (grito, explosão)")
    p.add_argument("--sem-vertical", action="store_true",
                   help="não gera a versão 9:16 pronta para TikTok/Shorts/Reels")
    p.add_argument("--fonte", action="append", default=[],
                   help="(teste) vídeo local no lugar de uma live; pode repetir")
    p.add_argument("--palavras", default="",
                   help="palavras extras que contam muito no chat, separadas por vírgula "
                        "(ex: assalto,roubo,fuga)")
    p.add_argument("--duracao", type=float, default=0,
                   help="para sozinho depois de N minutos (0 = até a live acabar)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def chat_loop(args, target: Target, clipper: Clipper, stop: threading.Event) -> None:
    det = HypeDetector(
        window=args.janela, threshold=args.sensibilidade, min_score=args.minimo,
        cooldown=args.intervalo, warmup=args.aquecimento,
    )
    for w in filter(None, (x.strip().lower() for x in args.palavras.split(","))):
        det.keywords[w] = 4.0

    best = {"ratio": 0.0, "ts": 0.0}
    started = time.time()

    def ticker() -> None:  # mantém a linha de base viva e garante clipes
        last_report = time.time()
        while not stop.is_set():
            now = time.time()
            fired = det.tick(now)
            if fired:  # disparo também pode vir só do relógio
                cat = det.category(fired)
                if clipper.auto_clip(fired, cat or "hype", title_for(cat)):
                    log.info("🔥 [%s] chat: %s", target.name, cat or "hype")
            ratio = det.current(now) / max(det.baseline, 1.0)
            if ratio > best["ratio"] and now - started > args.aquecimento:
                best.update(ratio=ratio, ts=now)
            # nenhum clipe há muito tempo: corta o momento mais diferente do período
            since = now - max(clipper._last_auto, started)
            if args.melhor_a_cada and since > args.melhor_a_cada * 60 and best["ratio"] >= 1.2:
                cat = det.category(best["ts"])
                if clipper.auto_clip(best["ts"], cat or "destaque", title_for(cat)):
                    log.info("⭐ [%s] melhor momento dos últimos %d min (%.1fx o normal)",
                             target.name, args.melhor_a_cada, best["ratio"])
                best.update(ratio=0.0, ts=0.0)
            if now - last_report > 60:
                last_report = now
                log.info("📊 [%s] chat agora %.0f / normal %.0f (%.1fx)",
                         target.name, det.current(now), det.baseline, ratio)
            stop.wait(1)

    threading.Thread(target=ticker, daemon=True).start()
    clipper.chat_category = det.category
    for msg in target.chat():
        if stop.is_set():
            return
        if args.comando and msg.is_mod and msg.text.lower().startswith(args.comando.lower()):
            log.info("%s pediu clipe no chat", msg.user)
            clipper.clip_async(msg.ts, f"chat-{msg.user}")
            continue
        fired = det.add(msg.ts, msg.text)
        if fired:
            cat = det.category(fired)
            if clipper.auto_clip(fired, cat or "hype", title_for(cat)):
                log.info("🔥 [%s] chat: %s (%.0f vs normal %.1f)", target.name,
                         cat or "hype", det.current(fired), det.baseline)


def audio_loop(name: str, rec: Recorder, clipper: Clipper, args, stop: threading.Event,
               chat_category=None) -> None:
    """Olha o volume de cada trecho novo: grito, risada alta, explosão."""
    det = LoudnessDetector(warmup=args.aquecimento)
    last = 0.0
    while not stop.is_set():
        for seg in rec.segments_after(last):
            last = seg.end
            if seg.path.exists() and det.add(seg.end, mean_volume(seg.path)):
                cat = chat_category(seg.end) if chat_category else ""
                if clipper.auto_clip(seg.end, cat or "audio", title_for(cat)):
                    log.info("🔊 [%s] pico de áudio (%s)", name, cat or "sem chat")
        stop.wait(1)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(message)s", datefmt="%H:%M:%S",
    )
    if not args.lives and not args.fonte:
        parser.error("informe o canal ou o link da live")
    try:
        targets: list[Target | str] = [resolve(x) for x in args.lives] + list(args.fonte)
    except ValueError as e:
        parser.error(str(e))

    stop = threading.Event()
    lives: list[tuple[str, Recorder, Clipper]] = []
    for n, t in enumerate(targets, 1):
        is_src = isinstance(t, str)
        name = Path(t).stem if is_src else t.name
        out = args.saida / name if len(targets) > 1 else args.saida
        rec = Recorder(
            out / ".buffer", stream_url=None if is_src else t.stream_url,
            quality=args.qualidade, source=t if is_src else None,
            buffer_seconds=max(args.buffer, int(args.antes + args.depois + 30)),
            realtime_input=is_src,
        )
        clipper = Clipper(rec, out, args.antes, args.depois,
                          vertical=not args.sem_vertical, label=name)
        clipper.cooldown = args.intervalo
        rec.start()
        lives.append((name, rec, clipper))
        log.info("[%d] gravando %s", n, name if is_src else f"{name} ({t.platform})")
        if not is_src and not args.sem_chat:
            threading.Thread(target=chat_loop, args=(args, t, clipper, stop),
                             daemon=True).start()
        if not args.sem_audio:
            threading.Thread(
                target=audio_loop, daemon=True,
                args=(name, rec, clipper, args, stop,
                      lambda ts, c=clipper: getattr(c, "chat_category", lambda _: "")(ts)),
            ).start()

    t0 = time.time()

    def expired() -> bool:
        return bool(args.duracao) and time.time() - t0 > args.duracao * 60

    log.info("ENTER corta todas • '2' ou '2 texto' + ENTER corta só a live 2 • Ctrl+C sai")
    try:
        while True:
            line = sys.stdin.readline()
            if not line:  # stdin fechado (ex: GitHub Actions): só espera
                while any(r.running for _, r, _ in lives) and not expired():
                    time.sleep(1)
                time.sleep(args.depois + 5)  # deixa clipes pendentes terminarem
                break
            now = time.time()
            first, _, rest = line.strip().partition(" ")
            if first.isdigit() and 1 <= int(first) <= len(lives):
                chosen, note = [lives[int(first) - 1]], rest.strip()
            else:
                chosen, note = lives, line.strip()
            for name, _, clipper in chosen:
                clipper.clip_async(now, note or "manual")
            log.info("marcado (%s)! salvando em %ss…",
                     ", ".join(n for n, _, _ in chosen), int(args.depois))
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        log.info("encerrando…")
        for _, rec, _ in lives:
            rec.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
