"""Envia clipes como rascunho para a caixa de entrada do TikTok (Content Posting API).

Uso:
  python -m clipador.tiktok login <code> <redirect_uri>   # troca o code por token
  python -m clipador.tiktok enviar <video.mp4>            # manda como rascunho

Precisa das variáveis TIKTOK_CLIENT_KEY e TIKTOK_CLIENT_SECRET. O refresh token
fica em tiktok_token.enc, cifrado com o client secret (o repositório é público).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://open.tiktokapis.com/v2"
TOKEN_FILE = Path("tiktok_token.enc")


def _req(url: str, data: bytes | None = None, headers: dict | None = None,
         method: str | None = None) -> dict:
    r = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        body = e.read()
        raise RuntimeError(f"TikTok {e.code}: {body[:300]!r}") from None
    return json.loads(body) if body else {}


def _openssl(args: list[str], data: bytes) -> bytes:
    secret = os.environ["TIKTOK_CLIENT_SECRET"].strip()
    return subprocess.run(
        ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-a", "-A", *args, "-pass", "env:K"],
        input=data, capture_output=True, check=True, env={**os.environ, "K": secret},
    ).stdout


def _save_refresh(token: str) -> None:
    TOKEN_FILE.write_bytes(_openssl([], token.encode()))


def _load_refresh() -> str:
    return _openssl(["-d"], TOKEN_FILE.read_bytes()).decode().strip()


def _token(form: dict) -> dict:
    form = {"client_key": os.environ["TIKTOK_CLIENT_KEY"].strip(),
            "client_secret": os.environ["TIKTOK_CLIENT_SECRET"].strip(), **form}
    res = _req(f"{API}/oauth/token/", urllib.parse.urlencode(form).encode(),
               {"Content-Type": "application/x-www-form-urlencoded",
                "Cache-Control": "no-cache"})
    if "access_token" not in res:
        raise RuntimeError(f"login TikTok falhou: {res}")
    return res


def login(code: str, redirect_uri: str) -> None:
    form = {"code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri}
    ver = Path("tiktok_verifier.txt")
    if ver.exists():  # PKCE
        form["code_verifier"] = ver.read_text().strip()
    res = _token(form)
    _save_refresh(res["refresh_token"])
    print("TikTok conectado (escopos: %s)" % res.get("scope"))


def access_token() -> str:
    old = _load_refresh()
    res = _token({"grant_type": "refresh_token", "refresh_token": old})
    if res.get("refresh_token") and res["refresh_token"] != old:
        _save_refresh(res["refresh_token"])  # o workflow faz commit do arquivo novo
    return res["access_token"]


def enviar(video: Path, token: str | None = None) -> str:
    """Manda o vídeo para a caixa de entrada (rascunho). Retorna o publish_id."""
    token = token or access_token()
    size = video.stat().st_size
    init = _req(
        f"{API}/post/publish/inbox/video/init/",
        json.dumps({"source_info": {"source": "FILE_UPLOAD", "video_size": size,
                                    "chunk_size": size, "total_chunk_count": 1}}).encode(),
        {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
    )
    if init.get("error", {}).get("code") not in (None, "ok"):
        raise RuntimeError(f"TikTok init: {init['error']}")
    data = init["data"]
    _req(data["upload_url"], video.read_bytes(),
         {"Content-Type": "video/mp4", "Content-Length": str(size),
          "Content-Range": f"bytes 0-{size - 1}/{size}"}, method="PUT")
    return data["publish_id"]


if __name__ == "__main__":
    cmd, *rest = sys.argv[1:] or ["?"]
    if cmd == "login" and len(rest) == 2:
        login(*rest)
    elif cmd == "enviar" and rest:
        tok = access_token()
        for f in rest:
            print(f"📲 rascunho no TikTok: {Path(f).name} ({enviar(Path(f), tok)})")
    else:
        print(__doc__)
        sys.exit(1)
