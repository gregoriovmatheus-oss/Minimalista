"""Caça os clipes de GTA que mais bombaram na Twitch (em português) e edita em 9:16.

  python -m clipador.virais <pasta_saida> [ja_feitos.lst] [horas=24] [quantos=8]

Usa a API oficial da Twitch (secrets TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET).
Baixa cada clipe com o streamlink, passa no make_vertical (título vermelho,
facecam, @viceclips.vibr + crédito do canal) e escreve o .txt no formato
"streamer | viral | dur | título (N views)". Imprime o caminho de cada mp4 novo.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .clipper import make_vertical

JOGOS = ["Grand Theft Auto VI", "Grand Theft Auto V"]
API = "https://api.twitch.tv/helix/"


def _token(cid: str, sec: str) -> str:
    dados = urllib.parse.urlencode({"client_id": cid, "client_secret": sec,
                                    "grant_type": "client_credentials"}).encode()
    with urllib.request.urlopen("https://id.twitch.tv/oauth2/token", dados, timeout=30) as r:
        return json.load(r)["access_token"]


def _get(path: str, params: dict, cid: str, tok: str) -> list:
    url = API + path + "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={"Client-Id": cid, "Authorization": f"Bearer {tok}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("data", [])


def escolher(clipes: list, feitos: set[str], quantos: int, min_views: int = 150) -> list:
    """Só português, sem repetir, os mais vistos; no máx. 2 por streamer."""
    por_canal: dict[str, int] = {}
    out = []
    for c in sorted(clipes, key=lambda c: -c.get("view_count", 0)):
        sid = _sid(c["id"])
        quem = c.get("broadcaster_name", "").lower()
        if (not (c.get("language") or "").startswith("pt") or c.get("view_count", 0) < min_views
                or any(sid in f for f in feitos) or por_canal.get(quem, 0) >= 2):
            continue
        por_canal[quem] = por_canal.get(quem, 0) + 1
        out.append(c)
        if len(out) >= quantos:
            break
    return out


def _sid(clip_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", clip_id)[-24:]


def titulo(t: str) -> str:
    t = re.sub(r"\s+", " ", t).strip().upper()
    return t[:60] if len(t) > 6 else "ISSO AQUI VIRALIZOU NO GTA"


def main(saida: Path, feitos_lst: Path | None, horas: int, quantos: int) -> None:
    cid, sec = os.environ.get("TWITCH_CLIENT_ID"), os.environ.get("TWITCH_CLIENT_SECRET")
    if not cid or not sec:
        print("sem TWITCH_CLIENT_ID/SECRET: nada a fazer", file=sys.stderr)
        return
    tok = _token(cid, sec)
    feitos = set(feitos_lst.read_text().split()) if feitos_lst and feitos_lst.exists() else set()
    desde = (datetime.now(timezone.utc) - timedelta(hours=horas)).strftime("%Y-%m-%dT%H:%M:%SZ")
    clipes: list = []
    for jogo in JOGOS:
        g = _get("games", {"name": jogo}, cid, tok)
        if g:
            clipes += _get("clips", {"game_id": g[0]["id"], "started_at": desde, "first": 100},
                           cid, tok)
    saida.mkdir(parents=True, exist_ok=True)
    for c in escolher(clipes, feitos, quantos):
        quem = re.sub(r"[^a-z0-9]", "", c["broadcaster_name"].lower()) or "twitch"
        quando = datetime.fromisoformat(c["created_at"].replace("Z", "+00:00"))
        stem = f"{quem}_{quando:%Y%m%d-%H%M%S}_viral_{_sid(c['id'])}"
        bruto, vert = saida / f"{stem}.mp4", saida / f"{stem}_vertical.mp4"
        r = subprocess.run(["streamlink", "--quiet", "-f", "-o", str(bruto), c["url"], "best"])
        if r.returncode or not bruto.exists():
            continue
        rodape = f"@viceclips.vibr  ·  twitch.tv/{quem}"
        if make_vertical(bruto, vert, titulo(c.get("title", "")), rodape) and vert.exists():
            dur = f"{round(c.get('duration', 0))}s"
            vert.with_suffix(".txt").write_text(
                f"{quem} | viral | {dur} | {c.get('title', '').strip()} "
                f"({c.get('view_count', 0)} views na Twitch)\n")
            print(vert)
        bruto.unlink(missing_ok=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        sys.exit(1)
    main(Path(a[0]), Path(a[1]) if len(a) > 1 else None,
         int(a[2]) if len(a) > 2 else 24, int(a[3]) if len(a) > 3 else 8)
