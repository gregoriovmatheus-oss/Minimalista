"""Índice organizado dos clipes para a descrição do release.

  python -m clipador.indice <pasta_enviados> <repo> <tag>  > notas.md

Agrupa por streamer (mais recentes primeiro), com hora, tipo, duração, o começo
da fala e um link direto pro vídeo. Clipes sem fala vão para o fim, recolhidos.
"""

from __future__ import annotations

import sys
from pathlib import Path

EMOJI = {"engracado": "😂", "assalto": "💰", "tenso": "😱", "meme": "🤡",
         "destaque": "⭐", "hype": "🔥", "audio": "🔊"}


def linha(txt: Path, base: str) -> tuple[str, str, bool]:
    stem = txt.name.removesuffix(".txt")
    partes = [p.strip() for p in txt.read_text(errors="ignore").split("|", 3)]
    nome, motivo, dur, fala = (partes + [""] * 4)[:4]
    try:  # alanzoka_20261119-213032_destaque_vertical
        hhmmss = stem.split("_")[1].split("-")[1]
        h, m = int(hhmmss[:2]), hhmmss[2:4]
        hora = f"{(h - 3) % 24:02d}:{m}"  # UTC -> Brasília
    except (IndexError, ValueError):
        hora = "--:--"
    tipo = next((k for k in EMOJI if k in stem.split("_")[2:3] + [motivo]), "hype")
    resumo = " ".join(fala.split()[:22])
    url = f"{base}/{stem}.mp4"
    texto = f"- [▶ **{hora}** {EMOJI[tipo]} {tipo} · {dur}]({url})"
    if resumo:
        texto += f" — _{resumo}…_"
    return nome or stem.split("_")[0], texto, bool(resumo)


def indice(pasta: Path, repo: str, tag: str) -> str:
    base = f"https://github.com/{repo}/releases/download/{tag}"
    grupos: dict[str, list[str]] = {}
    mudos: list[str] = []
    for t in sorted(pasta.glob("*_vertical.txt"), reverse=True):
        if not (pasta / f"{t.name.removesuffix('.txt')}.mp4").exists():
            continue
        nome, texto, fala = linha(t, base)
        (grupos.setdefault(nome, []) if fala else mudos).append(texto)
    total = sum(map(len, grupos.values())) + len(mudos)
    out = [f"**{total} clipes** · mais novos primeiro · toque em ▶ para abrir o vídeo.",
           "⭐ Os melhores escolhidos a dedo ficam em "
           f"[MELHORES.md](https://github.com/{repo}/blob/claude/loving-clarke-xzzliy/MELHORES.md).",
           ""]
    for nome in sorted(grupos):
        out += [f"### {nome} ({len(grupos[nome])})", *grupos[nome], ""]
    if mudos:
        out += [f"<details><summary>Sem fala ({len(mudos)})</summary>", "", *mudos, "",
                "</details>"]
    return "\n".join(out)[:120000]


if __name__ == "__main__":
    print(indice(Path(sys.argv[1]), sys.argv[2], sys.argv[3]))
