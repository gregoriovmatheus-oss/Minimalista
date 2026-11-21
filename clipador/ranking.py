"""Nota automática dos clipes (sem IA paga): fala + chat + tipo do momento.

  python -m clipador.ranking selecionar <pasta> <lista_de_nomes> [fração=0.4]

Lê <nome>.txt de cada clipe (linha 1 "streamer | motivo | duração | fala",
linha 2 opcional "chat: N msgs (R/min) | top: kkkk x12, ...") e imprime
"MANTER nome nota" / "DESCARTAR nome nota", melhores primeiro.
"""

from __future__ import annotations

import math
import re
import sys
import unicodedata
from pathlib import Path

REACAO = ["meu deus", "nao e possivel", "caralho", "c*ralho", "porra", "p*rra", "socorro",
          "que isso", "fudeu", "f*deu", "morri", "corre", "cuidado", "nossa senhora",
          "olha isso", "mano do ceu", "ta louco", "fala serio", "puta", "p*ta", "ai meu",
          "nao acredito", "kkk", "hahaha", "cade", "para para", "vai vai", "eita", "misericordia"]
RUIM = ["prime", "inscri", "sub ", "doacao", "doou", "pix", "loja", "adesivo", "tunar", "tuning",
        "menu", "patroc", "propaganda", "configurac", "trofeu", "salvar o jogo", "save"]
INGLES = {"you", "the", "is", "what", "i", "it", "to", "and", "are", "this", "that", "my"}
BORDAO = {
    "alanzoka": ["nao e possivel", "fala serio", "meu deus", "ai mano", "que isso", "socorro",
                 "nao nao nao", "mano do ceu"],
    "calango": ["velho", "fi ", "apavorado", "mano", "que loucura", "ai meu deus", "embacado",
                "doidao", "ta maluco"],
    "davyjones": ["easter egg", "segredo", "olha isso", "encontrei", "ovni", "misterio",
                  "ninguem sabia", "escondido"],
}
TIPO = {"assalto": 1.5, "engracado": 1.0, "tenso": 1.0, "meme": 0.5, "destaque": 0.5,
        "hype": 0.0, "audio": -0.5}


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def nota(txt: Path) -> float:
    linhas = txt.read_text(errors="ignore").splitlines() if txt.exists() else []
    partes = [p.strip() for p in (linhas or [""])[0].split("|", 3)] + [""] * 4
    fala = partes[3]
    f = _norm(fala)
    palavras = f.split()
    s = 0.0
    # fala: reações fortes, exclamações, quantidade de fala
    s += min(sum(f.count(r) for r in REACAO) * 0.6, 3.0)
    s += min(fala.count("!") * 0.3, 1.5)
    s += -2.0 if len(palavras) < 8 else min(len(palavras) / 40, 1.0)
    s -= min(sum(f.count(r) for r in RUIM) * 1.2, 3.6)
    if palavras and sum(w.strip(".,?!") in INGLES for w in palavras) / len(palavras) > 0.2:
        s -= 1.5  # quase só NPC falando em inglês
    # chat durante o clipe
    chat = next((ln for ln in linhas[1:] if ln.startswith("chat:")), "")
    m = re.search(r"\((\d+)/min", chat)
    if m:  # volume absoluto pesa pouco: chat grande é normal em streamer grande
        s += min(int(m.group(1)) / 60, 1.0)
    reps = [int(n) for n in re.findall(r" x(\d+)", chat)]
    if reps:
        s += min(max(reps) / 5, 2.0)
    if re.search(r"top:.*\bk[ks]*\b x\d+", chat):
        s += 1.5  # chat rindo
    m = re.search(r"x([\d.]+) do normal", chat)
    if m:  # chat explodiu em relação ao ritmo normal da live
        s += min(max(float(m.group(1)) - 1, 0) * 1.2, 3.0)
    # áudio e imagem: grito/risada (pico de volume) e ação na tela
    sin = next((ln for ln in linhas[1:] if ln.startswith("sinais:")), "")
    m = re.search(r"pico \+(\d+)", sin)
    if m:
        s += min(max(int(m.group(1)) - 8, 0) * 0.25, 2.5)
    m = re.search(r"movimento ([\d.]+)", sin)
    if m:
        a = float(m.group(1))
        s += -1.0 if a < 2.5 else min((a - 2.5) * 0.25, 1.5)  # parado = menu/loja
    # bordões de cada streamer
    quem = partes[0].lower()
    s += min(sum(f.count(b) for b in BORDAO.get(quem, [])) * 0.5, 1.5)
    # tipo do momento (vem no nome do arquivo)
    tipo = next((t for t in TIPO if f"_{t}" in txt.name), "hype")
    s += TIPO[tipo]
    return round(s, 2)


def _quando(nome: str) -> tuple[str, int]:
    """(streamer, segundos do dia) a partir de 'calango_20261119-210903_...'."""
    try:
        p = nome.split("_")
        h = p[1].split("-")[1]
        return p[0], int(p[1][:8]) * 86400 + int(h[:2]) * 3600 + int(h[2:4]) * 60 + int(h[4:6])
    except (IndexError, ValueError):
        return nome, 0


def selecionar(pasta: Path, nomes: list[str], fracao: float = 0.4,
               minimo: float = 3.0) -> list[tuple[str, float, bool]]:
    """Melhores ~40% (só os com nota ≥ mínimo), sem repetir o mesmo momento."""
    notas = sorted(((n, nota(pasta / f"{n}.txt")) for n in nomes), key=lambda x: -x[1])
    vagas = max(1, math.ceil(len(notas) * fracao)) if notas else 0
    escolhidos: list[str] = []
    for n, s in notas:
        quem, t = _quando(n)
        repetido = any(_quando(e)[0] == quem and abs(_quando(e)[1] - t) < 45 for e in escolhidos)
        if len(escolhidos) < vagas and s >= minimo and not repetido:
            escolhidos.append(n)
    if not escolhidos and notas:  # hora fraca: guarda só o melhor
        escolhidos.append(notas[0][0])
    return [(n, s, n in escolhidos) for n, s in notas]


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "selecionar":
        nomes = [ln.strip() for ln in Path(sys.argv[3]).read_text().split() if ln.strip()]
        fr = float(sys.argv[4]) if len(sys.argv) > 4 else 0.4
        for n, s, ok in selecionar(Path(sys.argv[2]), nomes, fr):
            print(f"{'MANTER' if ok else 'DESCARTAR'} {n} {s}")
    else:
        print(__doc__)
        sys.exit(1)
