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


_KOKORO = None


def _kokoro(text: str) -> Path:
    """Kokoro-82M (voz neural pt-BR, offline, bem mais natural que o Piper)."""
    global _KOKORO
    import types
    sys.modules.setdefault("spacy", types.ModuleType("spacy"))  # misaki.en importa, pt não usa
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline
    if _KOKORO is None:
        _KOKORO = KPipeline(lang_code="p")
    audio = np.concatenate([r.audio.numpy() for r in _KOKORO(
        text, voice=os.environ.get("KOKORO_VOZ", "pm_alex"), speed=1.08)])
    out = _tmp("wav")
    sf.write(out, audio, 24000)
    return out


def tts(text: str) -> Path:
    """ElevenLabs; sem crédito, Kokoro (neural, offline); por último, Piper."""
    try:
        return _eleven(text)
    except subprocess.CalledProcessError:
        pass
    try:
        return _kokoro(text)
    except Exception as e:  # noqa: BLE001 — sem kokoro/espeak: cai pro Piper
        print(f"kokoro indisponível ({e}); usando Piper", file=sys.stderr)
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


def _texts(lines: list[str], y0: float, size: int, red: bool = True,
           destaque: bool = False) -> str:
    font = _font()
    if not font:
        return ""
    f = font.replace(":", "\\:")
    vf = ""
    for i, ln in enumerate(lines):
        t = _tmp("txt")
        t.write_text(ln)
        # 1ª linha em amarelo quando traz o número/fato principal (destaque)
        amarelo = destaque and i == 0
        style = (f"box=1:boxcolor={'0xFACC15' if amarelo else '0xE11D48'}@0.95:boxborderw=14:"
                 "borderw=3:bordercolor=black" if red else "borderw=5:bordercolor=black")
        cor = "black" if amarelo else "white"
        if amarelo:
            style = style.replace("borderw=3:bordercolor=black", "borderw=0")
        vf += (f",drawtext=fontfile='{f}':textfile='{t}':fontsize={size}:fontcolor={cor}:"
               f"{style}:x=(w-tw)/2:y={y0}+{i * int(size * 1.45)}")
    return vf


_WHISPER = None


def palavras(audio: Path) -> list[tuple[str, float, float]]:
    """Tempo de cada palavra falada (faster-whisper); [] se indisponível."""
    global _WHISPER
    try:
        import soundfile as sf
        from faster_whisper import WhisperModel
        from scipy.signal import resample_poly
        if _WHISPER is None:
            _WHISPER = WhisperModel("small", device="cpu", compute_type="int8")
        a, sr = sf.read(str(audio), dtype="float32")
        a = resample_poly(a if a.ndim == 1 else a.mean(1), 16000, sr).astype("float32")
        segs, _ = _WHISPER.transcribe(a, language="pt", word_timestamps=True)
        return [(w.word.strip(), w.start, w.end) for sg in segs for w in sg.words if w.word.strip()]
    except Exception as e:  # noqa: BLE001
        print(f"sem legenda por palavra ({e})", file=sys.stderr)
        return []


def _legenda(ws: list[tuple[str, float, float]], dur: float,
             y: str = "h*0.66") -> str:
    """Legenda estilo TikTok: grupos de até 3 palavras, grandes, com a palavra falada em amarelo."""
    font = _font()
    if not font or not ws:
        return ""
    f = font.replace(":", "\\:")
    grupos, cur = [], []
    for w in ws:
        # até 3 palavras e ~15 letras por tela (cabe grande, sem estourar a largura)
        if cur and len(" ".join(x[0] for x in cur + [w])) > 15:
            grupos.append(cur)
            cur = []
        cur.append(w)
        if len(cur) == 3 or w[0][-1] in ".,!?":
            grupos.append(cur)
            cur = []
    if cur:
        grupos.append(cur)
    vf, size = "", 66
    for gi, g in enumerate(grupos):
        ini = g[0][1]
        fim = grupos[gi + 1][0][1] if gi + 1 < len(grupos) else dur
        pals = [w[0].upper().strip(".,") for w in g]
        size = 66
        while _largura(" ".join(pals), size) > W - 60 and size > 40:  # palavra enorme: encolhe
            size -= 2
        full = _largura(" ".join(pals), size)
        for k, (pal, (_, a, b)) in enumerate(zip(pals, g)):
            # cada palavra posicionada pela mesma medida (PIL), assim o amarelo cobre o branco certinho
            off = _largura(" ".join(pals[:k]) + " ", size) if k else 0
            x = f"(w-{full})/2+{off}"
            # o drawtext encosta o topo da tinta em y: compensa pra todas ficarem na mesma linha de base
            yw = f"{y}+{_topo(pal, size)}"
            t = _tmp("txt")
            t.write_text(pal)
            fimw = g[k + 1][1] if k + 1 < len(g) else fim
            for cor, de, ate in (("white", ini, fim), ("0xFACC15", a, fimw)):
                vf += (f",drawtext=fontfile='{f}':textfile='{t}':fontsize={size}:fontcolor={cor}:"
                       f"borderw=7:bordercolor=black:x={x}:y={yw}:"
                       f"enable='between(t,{de:.2f},{ate:.2f})'")
    return vf


def _topo(texto: str, size: int) -> int:
    from PIL import ImageFont
    return int(ImageFont.truetype(_font(), size).getbbox(texto, anchor="la")[1])


def _largura(texto: str, size: int) -> int:
    from PIL import ImageFont
    return int(ImageFont.truetype(_font(), size).getlength(texto))


def card(title: str, narration: str, bg: Path | None = None,
         prog: tuple[float, float] | None = None, legenda: bool = True) -> Path:
    """Tela de texto grande + narração. Fundo: quadro desfocado de um clipe ou gradiente."""
    audio = tts(narration)
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
         str(audio)], capture_output=True, text=True).stdout) + 0.35
    out = _tmp("mp4")
    # "|" no título força a quebra de linha (ex: "475 MILHÕES|EM 24H")
    lines = [ln for parte in title.upper().split("|") for ln in _wrap(parte.strip(), 16)][:4]
    destaque = any(ch.isdigit() for ch in lines[0])
    ws = palavras(audio) if legenda else []
    ytit = "h*0.11" if ws else f"(h-{len(lines) * 75})/2"
    txt = (_texts(lines, ytit, 64, destaque=destaque) + _legenda(ws, dur)
           + _texts([ASSINATURA], "h*0.86", 34, False))
    if prog:  # barra de progresso do vídeo inteiro (segura a retenção)
        a, b = prog
        txt += (f",drawbox=x=0:y=ih-14:w=iw:h=14:color=black@0.5:t=fill[pre];"
                f"color=c=0xFACC15:s={W}x14:r=30:d={dur:.3f}[bar];"
                f"[pre][bar]overlay=x='-W+W*({a:.4f}+{b - a:.4f}*t/{dur:.3f})':y=H-14"
                ":eval=frame:shortest=1")
    if bg and bg.suffix.lower() in (".png", ".jpg", ".jpeg"):
        # imagem de referência com zoom lento (efeito Ken Burns)
        src = ["-framerate", "30", "-loop", "1", "-t", f"{dur}", "-i", str(bg)]  # 30 = fps do zoompan
        base = (f"[0:v]scale=1440:2560:force_original_aspect_ratio=increase,crop=1440:2560,"
                f"zoompan=z='min(1+0.0009*on,1.25)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":d=1:s={W}x{H}:fps=30,eq=brightness=-0.08")
    elif bg:
        src = ["-ss", "1", "-t", f"{dur}", "-i", str(bg)]
        base = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                "boxblur=18:2,eq=brightness=-0.25,zoompan=z='1+0.0015*on':d=1:s=720x1280:fps=30")
    else:
        src = ["-f", "lavfi", "-t", f"{dur}", "-i",
               f"gradients=s={W}x{H}:c0=0x2b0040:c1=0xe11d48:c2=0x0b1d51:speed=0.015:r=30"]
        base = "[0:v]null"
    # flash branco curto na entrada (corte com impacto) + fade curto na saída;
    # voz com compressão leve e volume padrão de TikTok (-14 LUFS)
    fx = (f",fade=t=in:st=0:d=0.18:color=white,fade=t=out:st={dur - 0.15:.2f}:d=0.15")
    # whoosh (ruído rosa filtrado, 0,35 s) no corte + voz
    afx = ("[1:a]highpass=f=80,acompressor=threshold=-18dB:ratio=3:attack=5:release=80,"
           "loudnorm=I=-14:TP=-1.5:LRA=7,aresample=44100,aformat=channel_layouts=stereo[vz];"
           "anoisesrc=d=0.35:c=pink:a=0.5,highpass=f=900,lowpass=f=6000,"
           "afade=t=in:d=0.12,afade=t=out:st=0.12:d=0.23,volume=0.35,"
           "aformat=sample_rates=44100:channel_layouts=stereo[wh];"
           "[vz][wh]amix=inputs=2:duration=first:normalize=0,apad[a]")
    _ff(*src, "-i", str(audio), "-filter_complex", base + txt + fx + "[v];" + afx,
        "-map", "[v]", "-map", "[a]", "-t", f"{dur}", *_enc(), str(out))
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


def curiosidades(out: Path, itens: list = CURIOSIDADES) -> Path:
    """itens: (título, narração) ou (título, narração, imagem_de_fundo)."""
    n = len(itens)
    seco = _tmp("mp4")
    join([card(it[0], it[1], Path(it[2]) if len(it) > 2 else None, (k / n, (k + 1) / n))
          for k, it in enumerate(itens)], seco)
    return trilha(seco, out)


# Synthwave original gerado na hora (sem direitos autorais): baixo pulsando em colcheias,
# acorde "power chord" com harmônicos e progressão Lá-Fá-Dó-Sol a cada 2 s.
_RAIZ = "if(lt(mod(t,8),2),110,if(lt(mod(t,8),4),87.31,if(lt(mod(t,8),6),130.81,98)))"
_SYNTH = ("(" + "+".join(f"{1 / k:.3f}*sin(2*PI*{m}*{k}*({_RAIZ})*t)"
                         for m in (1, 1.5, 2) for k in (1, 2, 3)) + ")*0.06"
          f"+0.5*sin(2*PI*({_RAIZ})/2*t)*exp(-9*mod(t,0.25))"
          "+0.35*sin(2*PI*55*t)*exp(-25*mod(t,0.5))")


def trilha(video: Path, out: Path) -> Path:
    """Põe a trilha por baixo da voz, abaixando a música quando alguém fala (sidechain)."""
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
         str(video)], capture_output=True, text=True).stdout)
    _ff("-i", str(video), "-f", "lavfi", "-t", f"{dur:.2f}", "-i",
        f"aevalsrc='{_SYNTH}':s=44100:c=stereo",
        "-filter_complex",
        "[1:a]lowpass=f=2400,aecho=0.8:0.7:180:0.25,volume=0.22,"
        f"afade=t=out:st={dur - 1.2:.2f}:d=1.2[m];"
        "[0:a]asplit[v1][v2];[m][v2]sidechaincompress=threshold=0.05:ratio=6:attack=20:release=300[md];"
        "[v1][md]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.89[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart", str(out))
    print(f"🎵 {out}")
    return out


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
