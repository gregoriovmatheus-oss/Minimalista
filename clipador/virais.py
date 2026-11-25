"""Top 5 de clipes de GTA 6 mais vistos na Twitch (PT-BR): manhã, tarde e noite.

  python -m clipador.virais <pasta_saida> <ja_feitos.lst>

Roda a cada poucos minutos; sozinho decide o lote pelo horário de Brasília:
  manhã  pronto até 10h (roda a partir de 9:30)
  tarde  pronto até 17h (a partir de 16:30)
  noite  pronto até 21h (a partir de 20:30)
Cada lote pega os 5 mais assistidos das últimas 24h que ainda NÃO foram usados
(nem hoje, nem antes): se o 1º da manhã continua no topo à tarde, ele é pulado
e entra o próximo. Usa a API oficial da Twitch (secrets TWITCH_CLIENT_ID /
TWITCH_CLIENT_SECRET). Imprime o caminho de cada mp4 novo.
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

JOGO = "Grand Theft Auto VI"
API = "https://api.twitch.tv/helix/"
BRT = timezone(timedelta(hours=-3))
LOTES = [("manha", 9, 30, "manhã"), ("tarde", 16, 30, "tarde"), ("noite", 20, 30, "noite")]
TOP = 5


def _token(cid: str, sec: str) -> str:
    dados = urllib.parse.urlencode({"client_id": cid, "client_secret": sec,
                                    "grant_type": "client_credentials"}).encode()
    with urllib.request.urlopen("https://id.twitch.tv/oauth2/token", dados, timeout=30) as r:
        return json.load(r)["access_token"]


def _get(path: str, params: dict, cid: str, tok: str) -> dict:
    url = API + path + "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={"Client-Id": cid, "Authorization": f"Bearer {tok}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _sid(clip_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", clip_id)[-24:]


def lote_agora(agora: datetime, feitos: set[str]) -> tuple[str, str, int] | None:
    """(lote, dia, já_prontos) que deve rodar agora, ou None se completo / fora de hora."""
    agora = agora.astimezone(BRT)
    dia = f"{agora:%d%m}"
    atual = None
    for nome, h, m, _ in LOTES:
        if (agora.hour, agora.minute) >= (h, m):
            atual = nome
    if atual is None:
        return None
    prontos = sum(f"_top5_{atual}_{dia}_" in f and f.endswith("_vertical.mp4") for f in feitos)
    return (atual, dia, prontos) if prontos < TOP else None


def escolher(clipes: list, feitos: set[str], min_views: int = 30) -> list:
    """Português, mais vistos primeiro, sem nenhum que já tenha sido usado."""
    return [c for c in sorted(clipes, key=lambda c: -c.get("view_count", 0))
            if (c.get("language") or "").startswith("pt") and c.get("view_count", 0) >= min_views
            and not any(_sid(c["id"]) in f for f in feitos)]


def titulo(t: str) -> str:
    t = re.sub(r"\s+", " ", t).strip().upper()
    return t[:60] if len(t) > 6 else "ISSO AQUI VIRALIZOU NO GTA 6"


def buscar(cid: str, tok: str) -> list:
    g = _get("games", {"name": JOGO}, cid, tok).get("data")
    if not g:
        return []
    desde = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    clipes, cursor = [], None
    for _ in range(5):  # até 500 clipes (5 páginas)
        p = {"game_id": g[0]["id"], "started_at": desde, "first": 100}
        if cursor:
            p["after"] = cursor
        r = _get("clips", p, cid, tok)
        clipes += r.get("data", [])
        cursor = r.get("pagination", {}).get("cursor")
        if not cursor:
            break
    return clipes


def main(saida: Path, feitos_lst: Path) -> None:
    cid, sec = os.environ.get("TWITCH_CLIENT_ID"), os.environ.get("TWITCH_CLIENT_SECRET")
    if not cid or not sec:
        return
    feitos = set(feitos_lst.read_text().split()) if feitos_lst.exists() else set()
    lote = lote_agora(datetime.now(timezone.utc), feitos)
    if not lote:
        return
    nome, dia, pos = lote  # continua de onde parou se a rodada caiu no meio
    tok = _token(cid, sec)
    saida.mkdir(parents=True, exist_ok=True)
    for c in escolher(buscar(cid, tok), feitos):
        if pos >= TOP:
            break
        quem = re.sub(r"[^a-z0-9]", "", c["broadcaster_name"].lower()) or "twitch"
        quando = datetime.fromisoformat(c["created_at"].replace("Z", "+00:00"))
        stem = f"{quem}_{quando:%Y%m%d-%H%M%S}_top5_{nome}_{dia}_{pos + 1}_{_sid(c['id'])}"
        bruto, vert = saida / f"{stem}.mp4", saida / f"{stem}_vertical.mp4"
        r = subprocess.run(["streamlink", "--quiet", "-f", "-o", str(bruto), c["url"], "best"])
        if r.returncode or not bruto.exists():
            continue  # não baixou: o próximo da lista assume a posição
        rodape = f"@viceclips.vibr  ·  twitch.tv/{quem}"
        if make_vertical(bruto, vert, titulo(c.get("title", "")), rodape) and vert.exists():
            pos += 1
            rotulo = next(r for n, _, _, r in LOTES if n == nome)
            vert.with_suffix(".txt").write_text(
                f"{quem} | top5 {rotulo} {dia[:2]}/{dia[2:]} #{pos} | "
                f"{round(c.get('duration', 0))}s | {c.get('title', '').strip()} "
                f"({c.get('view_count', 0)} views na Twitch)\n")
            print(vert)
        bruto.unlink(missing_ok=True)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
