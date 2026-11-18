"""Vídeos autorais 9:16 com narração (ElevenLabs): Top 3, Quiz A/B e Curiosidades.

  python -m clipador.autoral top3 saida.mp4 clipe1.mp4 clipe2.mp4 clipe3.mp4
  python -m clipador.autoral quiz saida.mp4 clipeA.mp4 clipeB.mp4
  python -m clipador.autoral curiosidades saida.mp4

O nome do streamer é tirado do nome do arquivo (ex: calango_2026..._vertical.mp4).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .clipper import _font, _wrap

W, H = 720, 1280
VOICE = os.environ.get("VOZ_ID", "TX3LPaxmHKxFdv7VOQHJ")  # Liam: criador de conteúdo
ASSINATURA = os.environ.get("ASSINATURA", "@viceclips.vibr")
TMP = Path(tempfile.mkdtemp(prefix="autoral_"))
_n = 0


def _tmp(ext: str) -> Path:
    global _n
    _n += 1
    return TMP / f"p{_n:03d}.{ext}"


def _ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


PIPER = Path(os.environ.get("PIPER_VOZ", Path(__file__).resolve().parent.parent
                             / "vozes" / "pt_BR-faber-medium.onnx"))


def tts(text: str) -> Path:
    """ElevenLabs; se faltar crédito, usa o Piper (voz pt-BR gratuita, offline)."""
    try:
        return _eleven(text)
    except subprocess.CalledProcessError:
        out = _tmp("wav")
        subprocess.run([sys.executable, "-m", "piper", "-m", str(PIPER), "-f", str(out),
                        "--length-scale", "0.88"], input=text.encode(), check=True,
                       capture_output=True)
        return out


def _eleven(text: str) -> Path:
    out = _tmp("mp3")
    body = json.dumps({"text": text, "model_id": "eleven_multilingual_v2",
                       "voice_settings": {"stability": 0.4, "similarity_boost": 0.8,
                                          "style": 0.5}})
    subprocess.run(
        ["curl", "-sS", "--fail", "-X", "POST", "-o", str(out),
         f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}?output_format=mp3_44100_128",
         "-H", "Content-Type: application/json",
         "-H", f"xi-api-key: {os.environ.get('ELEVENLABS_API_KEY', 'x')}", "-d", body],
        check=True,
    )
    return out


def _texts(lines: list[str], y0: float, size: int, red: bool = True) -> str:
    font = _font()
    if not font:
        return ""
    f = font.replace(":", "\\:")
    vf = ""
    for i, ln in enumerate(lines):
        t = _tmp("txt")
        t.write_text(ln)
        style = ("box=1:boxcolor=0xE11D48@0.95:boxborderw=14:borderw=3:bordercolor=black"
                 if red else "borderw=5:bordercolor=black")
        vf += (f",drawtext=fontfile='{f}':textfile='{t}':fontsize={size}:fontcolor=white:"
               f"{style}:x=(w-tw)/2:y={y0}+{i * int(size * 1.45)}")
    return vf


def card(title: str, narration: str, bg: Path | None = None) -> Path:
    """Tela de texto grande + narração. Fundo: quadro desfocado de um clipe ou gradiente."""
    audio = tts(narration)
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
         str(audio)], capture_output=True, text=True).stdout) + 0.35
    out = _tmp("mp4")
    lines = _wrap(title.upper(), 16)[:4]
    txt = _texts(lines, f"(h-{len(lines) * 75})/2", 64) + _texts([ASSINATURA], "h*0.86", 34, False)
    if bg:
        src = ["-ss", "1", "-t", f"{dur}", "-i", str(bg)]
        base = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                "boxblur=18:2,eq=brightness=-0.25,zoompan=z='1+0.0015*on':d=1:s=720x1280:fps=30")
    else:
        src = ["-f", "lavfi", "-t", f"{dur}", "-i",
               f"gradients=s={W}x{H}:c0=0x2b0040:c1=0xe11d48:c2=0x0b1d51:speed=0.015:r=30"]
        base = "[0:v]null"
    _ff(*src, "-i", str(audio), "-filter_complex", base + txt + "[v]",
        "-map", "[v]", "-map", "1:a", "-t", f"{dur}", *_enc(), str(out))
    return out


def _enc() -> list[str]:
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
            "-r", "30", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "160k"]


def norm(clip: Path) -> Path:
    out = _tmp("mp4")
    _ff("-i", str(clip), "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2", *_enc(), str(out))
    return out


def join(parts: list[Path], out: Path) -> Path:
    lst = _tmp("txt")
    lst.write_text("".join(f"file '{p}'\n" for p in parts))
    _ff("-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
        "-movflags", "+faststart", str(out))
    print(f"🎬 {out}")
    return out


def nome(clip: Path) -> str:
    return clip.name.split("_")[0]


def top3(out: Path, clips: list[Path]) -> Path:
    c3, c2, c1 = clips[:3]
    parts = [card("TOP 3 MOMENTOS MAIS INSANOS DE HOJE",
                  "Os três momentos mais insanos das lives de hoje. Fica até o final, "
                  "porque o número um é absurdo.", c1)]
    for n, c, extra in ((3, c3, ""), (2, c2, ""), (1, c1, " E esse aqui... olha isso.")):
        parts += [card(f"#{n} {nome(c)}", f"Número {['um','dois','três'][n-1]}: {nome(c)}.{extra}",
                       c), norm(c)]
    parts.append(card("QUAL FOI O MELHOR? COMENTA AÍ",
                      "E aí, qual foi o melhor? Comenta aí e segue pra não perder os próximos.", c1))
    return join(parts, out)


def quiz(out: Path, a: Path, b: Path) -> Path:
    parts = [card(f"QUEM MANDOU MELHOR HOJE? {nome(a)} OU {nome(b)}",
                  f"Quem mandou melhor hoje: {nome(a)} ou {nome(b)}? Assiste os dois e vota.", a),
             card(f"A: {nome(a)}", f"Opção A: {nome(a)}.", a), norm(a),
             card(f"B: {nome(b)}", f"Opção B: {nome(b)}.", b), norm(b),
             card("COMENTA A OU B", "Comenta A ou B. Eu quero ver quem vai ganhar essa.", b)]
    return join(parts, out)


CURIOSIDADES = [
    ("4 COISAS QUE VOCÊ PRECISA SABER DO GTA VI",
     "Quatro coisas sobre GTA seis que todo fã precisa saber. A última é a mais insana."),
    ("O MAPA SE CHAMA LEONIDA",
     "O jogo se passa em Leonida, um estado fictício inspirado na Flórida."),
    ("VICE CITY ESTÁ DE VOLTA",
     "E sim: Vice City está de volta, a cidade mais icônica da série."),
    ("LUCIA E JASON: DOIS PROTAGONISTAS",
     "Os protagonistas são Lucia e Jason, um casal de criminosos no estilo Bonnie e Clyde."),
    ("O 1º TRAILER QUEBROU RECORDE NO YOUTUBE",
     "E o primeiro trailer quebrou o recorde de vídeo mais visto em vinte e quatro horas "
     "no YouTube, fora clipes de música."),
    ("O QUE VOCÊ MAIS QUER VER? COMENTA",
     "E você, o que mais quer ver no GTA seis? Comenta aí e segue pra mais."),
]


def curiosidades(out: Path, itens: list[tuple[str, str]] = CURIOSIDADES) -> Path:
    return join([card(t, n) for t, n in itens], out)


if __name__ == "__main__":
    cmd, out, *clips = sys.argv[1:] + [""] * (2 - len(sys.argv[1:]))
    if cmd == "top3":
        top3(Path(out), [Path(c) for c in clips])
    elif cmd == "quiz":
        quiz(Path(out), *[Path(c) for c in clips[:2]])
    elif cmd == "curiosidades":
        curiosidades(Path(out))
    else:
        print(__doc__)
        sys.exit(1)
