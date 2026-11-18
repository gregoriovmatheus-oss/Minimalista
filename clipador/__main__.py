"""Linha de comando: python -m clipador <canal-da-twitch | link-da-live>"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from pathlib import Path

from .clipper import Clipper
from .detector import HypeDetector
from .platform import Target, resolve
from .recorder import Recorder

log = logging.getLogger("clipador")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="clipador",
        description="Acompanha uma live da Twitch ou do YouTube e corta clipes ao vivo.",
    )
    p.add_argument("live", nargs="?",
                   help="canal da Twitch (ex: gaules) ou link da live (Twitch ou YouTube)")
    p.add_argument("-q", "--qualidade", default="best", help="qualidade do streamlink (padrão: best)")
    p.add_argument("-o", "--saida", default="clipes", type=Path, help="pasta dos clipes")
    p.add_argument("--antes", type=float, default=30, help="segundos antes do momento (padrão: 30)")
    p.add_argument("--depois", type=float, default=10, help="segundos depois do momento (padrão: 10)")
    p.add_argument("--buffer", type=int, default=180, help="segundos guardados em disco (padrão: 180)")
    p.add_argument("--sem-chat", action="store_true", help="desliga o corte automático pelo chat")
    p.add_argument("--sensibilidade", type=float, default=2.5,
                   help="quantas vezes acima do normal o chat precisa ficar (padrão: 2.5)")
    p.add_argument("--minimo", type=float, default=15, help="pontuação mínima na janela (padrão: 15)")
    p.add_argument("--janela", type=float, default=10, help="janela do chat em segundos (padrão: 10)")
    p.add_argument("--intervalo", type=float, default=45, help="tempo mínimo entre clipes automáticos")
    p.add_argument("--aquecimento", type=float, default=60,
                   help="segundos observando o chat antes de cortar (padrão: 60)")
    p.add_argument("--comando", default="!clip",
                   help="comando que mods/streamer usam no chat para cortar ('' desliga)")
    p.add_argument("--fonte", help="(teste) entrada do ffmpeg no lugar da Twitch, ex: video.mp4")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def chat_loop(args, target: Target, clipper: Clipper, stop: threading.Event) -> None:
    det = HypeDetector(
        window=args.janela, threshold=args.sensibilidade, min_score=args.minimo,
        cooldown=args.intervalo, warmup=args.aquecimento,
    )

    def ticker() -> None:  # mantém a linha de base viva mesmo com chat parado
        while not stop.is_set():
            det.tick(time.time())
            stop.wait(1)

    threading.Thread(target=ticker, daemon=True).start()
    for msg in target.chat():
        if stop.is_set():
            return
        if args.comando and msg.is_mod and msg.text.lower().startswith(args.comando.lower()):
            log.info("%s pediu clipe no chat", msg.user)
            clipper.clip_async(msg.ts, f"chat-{msg.user}")
            continue
        fired = det.add(msg.ts, msg.text)
        if fired:
            log.info("🔥 hype no chat (%.0f vs normal %.1f)", det.current(fired), det.baseline)
            clipper.clip_async(fired, "hype")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(message)s", datefmt="%H:%M:%S",
    )
    if not args.live and not args.fonte:
        build_parser().error("informe o canal ou o link da live")
    target = None
    if args.live:
        try:
            target = resolve(args.live)
        except ValueError as e:
            build_parser().error(str(e))

    buffer_dir = args.saida / ".buffer"
    rec = Recorder(
        buffer_dir, stream_url=target.stream_url if target else None, quality=args.qualidade, source=args.fonte,
        buffer_seconds=max(args.buffer, int(args.antes + args.depois + 30)),
        realtime_input=bool(args.fonte),
    )
    clipper = Clipper(rec, args.saida, args.antes, args.depois)
    stop = threading.Event()

    rec.start()
    log.info("gravando %s — aperte ENTER para cortar, Ctrl+C para sair",
             f"{target.name} ({target.platform})" if target else args.fonte)

    if target and not args.sem_chat:
        threading.Thread(target=chat_loop, args=(args, target, clipper, stop),
                         daemon=True).start()

    try:
        while True:
            line = sys.stdin.readline()
            if not line:  # stdin fechado: só espera a gravação
                while rec.running:
                    time.sleep(1)
                break
            note = line.strip() or "manual"
            clipper.clip_async(time.time(), note)
            log.info("marcado! salvando em %ss…", int(args.depois))
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        log.info("encerrando…")
        rec.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
