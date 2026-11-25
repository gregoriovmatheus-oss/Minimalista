"""Gera a galeria (GitHub Pages) dos clipes: ver e baixar no celular com um toque.

  python -m clipador.galeria <pasta_com_mp4_e_txt> [MELHORES.md]

Escreve <pasta>/index.html e uma capa .jpg para cada vídeo.
"""

from __future__ import annotations

import html
import json
import subprocess
import sys
from pathlib import Path

PAGE = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Viceclips Clipes</title>
<style>
:root{--bg:#0d0a14;--card:#18121f;--line:#2c2238;--fg:#f4eef8;--mut:#a596b4;--acc:#e11d48;--acc2:#22d3ee;color-scheme:dark}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px system-ui,-apple-system,sans-serif;
padding:calc(14px + env(safe-area-inset-top)) max(14px,env(safe-area-inset-right)) 40px max(14px,env(safe-area-inset-left))}
h1{font:800 26px/1 system-ui;margin:0 0 4px;letter-spacing:.02em}h1 b{color:var(--acc)}
.sub{color:var(--mut);margin:0 0 12px;font-size:13px}
.chips{display:flex;gap:8px;overflow-x:auto;padding-bottom:10px;position:sticky;top:0;background:var(--bg);z-index:2;padding-top:6px}
.chip{flex:none;font:600 14px system-ui;color:var(--fg);background:var(--card);border:1px solid var(--line);border-radius:999px;padding:8px 14px}
.chip.on{background:var(--acc);border-color:var(--acc)}
.grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fill,minmax(260px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden;min-width:0}
video{display:block;width:100%;aspect-ratio:9/16;background:#000}
.i{padding:10px 12px 12px;display:grid;gap:8px}
.m{display:flex;gap:8px;flex-wrap:wrap;font-size:13px;color:var(--mut)}.who{color:var(--acc2);font-weight:700;text-transform:uppercase}
.star{color:#facc15;font-weight:700}
.f{font-size:13px;color:var(--mut);display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.b{display:block;text-align:center;font:700 15px system-ui;background:var(--acc);color:#fff;text-decoration:none;border-radius:10px;padding:13px}
</style></head><body>
<h1>VICE<b>CLIPS</b></h1>
<p class="sub">Toque no vídeo para ver. <b>Baixar</b> salva no iPhone (Arquivos → Downloads; de lá, Compartilhar → Salvar vídeo). Atualiza sozinha a cada ~20 min.</p>
<div class="chips" id="chips"></div><main class="grid" id="g"></main>
<script>
const C=__DATA__;let f="⭐ Melhores";
if(!C.some(c=>c.best))f="Todos";
function chips(){const n=["⭐ Melhores","Todos",...new Set(C.filter(c=>c.lote).map(c=>c.lote.replace("top5","🏆 Top 5"))),...new Set(C.map(c=>c.who))];
document.getElementById("chips").innerHTML=n.map(x=>`<button class="chip ${x==f?"on":""}">${x}</button>`).join("");
document.querySelectorAll(".chip").forEach((b,i)=>b.onclick=()=>{f=n[i];draw()})}
function draw(){chips();const l=C.filter(c=>f=="Todos"||(f=="⭐ Melhores"?c.best:(c.who==f||c.lote.replace("top5","🏆 Top 5")==f)));
if(f.startsWith("🏆"))l.sort((a,b)=>a.pos-b.pos);
document.getElementById("g").innerHTML=l.length?l.map(c=>`<article class="card">
<video controls playsinline preload="none" poster="${c.poster}" src="${c.file}"></video>
<div class="i"><div class="m"><span class="who">${c.who}</span><span>${c.when}</span><span>${c.dur}</span>${c.pos=="0"?'<span class="star">🎬 vídeo completo</span>':c.pos?`<span class="star">🏆 ${c.pos}º</span>`:c.best?'<span class="star">⭐ escolhido</span>':""}</div>
<div class="f">${c.fala}</div><a class="b" href="${c.file}" download>⬇ Baixar</a></div></article>`).join(""):'<p class="sub">Nenhum clipe aqui ainda.</p>'}
draw();
</script></body></html>"""


# Login do TikTok (uma vez só): entra, volta aqui com o code e salva no GitHub,
# que troca o code pelo token (workflow tiktok-login.yml). Nada de secret aqui.
TIKTOK = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Conectar TikTok</title>
<style>body{margin:0;background:#0d0a14;color:#f4eef8;font:16px system-ui;padding:24px 16px}
h1{font:800 24px system-ui}input,a,button{display:block;width:100%;box-sizing:border-box;font:600 16px system-ui;
border-radius:10px;padding:14px;margin:10px 0;border:1px solid #2c2238;background:#18121f;color:#f4eef8;text-align:center;text-decoration:none}
.b{background:#e11d48;border-color:#e11d48;color:#fff}p{color:#a596b4}</style></head><body>
<h1>Conectar o TikTok</h1><div id="x"></div>
<script>
const R=location.origin+location.pathname,q=new URLSearchParams(location.search),x=document.getElementById("x");
const BR="claude/loving-clarke-xzzliy",REPO="gregoriovmatheus-oss/Minimalista";
if(q.get("code")){const v=q.get("code")+" "+R;
x.innerHTML=`<p>✅ Login feito. Agora toque no botão, e no GitHub toque em <b>Commit changes</b> (duas vezes). Faça isso em até 5 minutos.</p>
<a class="b" href="https://github.com/${REPO}/new/${BR}?filename=tiktok_code.txt&value=${encodeURIComponent(v)}">Salvar no GitHub</a>`}
else{x.innerHTML=`<p>Cole o <b>Client key</b> do seu app (developers.tiktok.com) e toque em Entrar.</p>
<input id="k" placeholder="Client key" autocapitalize="off"><button class="b" id="go">Entrar com TikTok</button>`;
document.getElementById("go").onclick=()=>{const k=document.getElementById("k").value.trim();if(!k)return;
location.href="https://www.tiktok.com/v2/auth/authorize/?"+new URLSearchParams({client_key:k,
scope:"user.info.basic,video.upload",response_type:"code",redirect_uri:R,state:"vc"})}}
</script></body></html>"""


def build(pasta: Path, melhores: Path | None = None) -> Path:
    best = melhores.read_text() if melhores and melhores.exists() else ""
    itens = []
    for mp4 in sorted(pasta.glob("*_vertical.mp4"), reverse=True):
        stem = mp4.stem
        txt = mp4.with_suffix(".txt")
        linha = (txt.read_text(errors="ignore").splitlines() or [""])[0] if txt.exists() else ""
        partes = [p.strip() for p in linha.split("|", 3)] + [""] * 4
        poster = mp4.with_suffix(".jpg")
        if not poster.exists():
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", "3", "-i", str(mp4),
                            "-frames:v", "1", "-vf", "scale=360:-1", "-q:v", "6", str(poster)])
        try:
            h, m = int(stem.split("_")[1].split("-")[1][:2]), stem.split("_")[1].split("-")[1][2:4]
            d = stem.split("_")[1][6:8] + "/" + stem.split("_")[1][4:6]
            when = f"{d} {(h - 3) % 24:02d}:{m}"
        except (IndexError, ValueError):
            when = ""
        itens.append({"file": mp4.name, "poster": poster.name, "who": stem.split("_")[0],
                      "when": when, "dur": partes[2], "best": stem in best or "_top5_" in stem,
                      "lote": partes[1].split(" #")[0] if partes[1].startswith("top5") else "",
                      "pos": partes[1].split("#")[-1] if partes[1].startswith("top5") else "",
                      "fala": html.escape(" ".join(partes[3].split()[:30]))})
    (pasta / "tiktok.html").write_text(TIKTOK)
    out = pasta / "index.html"
    out.write_text(PAGE.replace("__DATA__", json.dumps(itens, ensure_ascii=False)
                                .replace("</", "<\\/")))
    return out


if __name__ == "__main__":
    print(build(Path(sys.argv[1]), Path(sys.argv[2]) if len(sys.argv) > 2 else None))
