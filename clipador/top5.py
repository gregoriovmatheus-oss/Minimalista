"""Monta o vídeo "TOP 5 GTA 6" (contagem 5 → 1) a partir dos 5 clipes do lote.

  python -m clipador.top5 <pasta_com_os_5> <manha|tarde|noite> <ddmm>

Na pasta: os *_top5_<lote>_<ddmm>_<pos>_*_vertical.mp4 (já em 9:16, com crédito
do streamer no rodapé). Gera capa de 1,8 s + os clipes do 5º ao 1º com o número
grande na tela, e imprime o caminho do mp4 (com .txt para a galeria).
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .clipper import _font

NOME = {"manha": "DA MANHÃ", "tarde": "DA TARDE", "noite": "DA NOITE"}
ROTULO = {"manha": "manhã", "tarde": "tarde", "noite": "noite"}


def _esc(t: str) -> str:
    return t.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’").replace("%", "\\%")


def clipes(pasta: Path, lote: str, dia: str) -> list[tuple[int, Path]]:
    achados = {}
    for f in pasta.glob(f"*_top5_{lote}_{dia}_*_vertical.mp4"):
        m = re.search(rf"_top5_{lote}_{dia}_([1-5])_", f.name)
        if m:
            achados[int(m.group(1))] = f
    return sorted(achados.items(), reverse=True)  # 5, 4, 3, 2, 1


def montar(pasta: Path, lote: str, dia: str) -> Path | None:
    lista = clipes(pasta, lote, dia)
    if len(lista) < 5:
        return None
    fonte = _font()
    ff = f":fontfile='{fonte}'" if fonte else ""
    agora = datetime.now(timezone.utc)
    out = pasta / f"top5_{agora:%Y%m%d-%H%M%S}_top5_{lote}_{dia}_0_video_vertical.mp4"
    cmd = ["ffmpeg", "-loglevel", "error", "-y",
           "-f", "lavfi", "-i", "color=c=0x0d0a14:s=720x1280:r=30:d=1.8",
           "-f", "lavfi", "-t", "1.8", "-i", "anullsrc=r=44100:cl=stereo"]
    for _, f in lista:
        cmd += ["-i", str(f)]
    capa = (f"[0:v]drawtext=text='TOP 5'{ff}:fontsize=170:fontcolor=white:x=(w-tw)/2:y=h*0.30"
            f":borderw=6:bordercolor=0xE11D48,"
            f"drawtext=text='GTA 6'{ff}:fontsize=120:fontcolor=0xE11D48:x=(w-tw)/2:y=h*0.46,"
            f"drawtext=text='{_esc(NOME[lote])}  {dia[:2]}/{dia[2:]}'{ff}:fontsize=58:"
            f"fontcolor=white:x=(w-tw)/2:y=h*0.60,"
            f"drawtext=text='@viceclips.vibr'{ff}:fontsize=40:fontcolor=0xa596b4:x=(w-tw)/2:y=h*0.86,"
            "format=yuv420p,setsar=1[v0];[1:a]aformat=sample_rates=44100:channel_layouts=stereo[a0];")
    partes = "[v0][a0]"
    for i, (pos, _) in enumerate(lista, start=2):
        capa += (f"[{i}:v]scale=720:1280:force_original_aspect_ratio=decrease,"
                 "pad=720:1280:(ow-iw)/2:(oh-ih)/2,fps=30,"
                 f"drawtext=text='#{pos}'{ff}:fontsize=150:fontcolor=white:borderw=8:"
                 "bordercolor=0xE11D48:x=w-tw-30:y=h*0.47:enable='lt(t,4)',"
                 f"format=yuv420p,setsar=1[v{i}];"
                 f"[{i}:a]aformat=sample_rates=44100:channel_layouts=stereo[a{i}];")
        partes += f"[v{i}][a{i}]"
    capa += f"{partes}concat=n={len(lista) + 1}:v=1:a=1[v][a]"
    cmd += ["-filter_complex", capa, "-map", "[v]", "-map", "[a]", "-c:v", "libx264",
            "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-b:a", "160k",
            "-movflags", "+faststart", str(out)]
    if subprocess.run(cmd).returncode or not out.exists():
        return None
    quem = ", ".join(f.name.split("_")[0] for _, f in reversed(lista))
    out.with_suffix(".txt").write_text(
        f"top5 | top5 {ROTULO[lote]} {dia[:2]}/{dia[2:]} #0 | vídeo completo | "
        f"TOP 5 GTA 6 {NOME[lote]}: {quem}\n")
    return out


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    r = montar(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
    if not r:
        sys.exit(1)
    print(r)
