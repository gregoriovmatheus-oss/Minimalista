import json
import subprocess
import time
from pathlib import Path

import pytest

from clipador.chat import parse_privmsg
from clipador.clipper import Clipper
from clipador.detector import HypeDetector, message_score, DEFAULT_KEYWORDS
from clipador.platform import resolve
from clipador.recorder import Recorder
from clipador.youtube_chat import initial_continuation, parse_actions, video_id_from_url


# ---------------------------------------------------------------- plataformas
@pytest.mark.parametrize("alvo,plat,url", [
    ("gaules", "twitch", "https://www.twitch.tv/gaules"),
    ("https://www.twitch.tv/Gaules", "twitch", "https://www.twitch.tv/gaules"),
    ("twitch.tv/casimiro/", "twitch", "https://www.twitch.tv/casimiro"),
    ("https://www.youtube.com/watch?v=abcdefghijk", "youtube",
     "https://www.youtube.com/watch?v=abcdefghijk"),
    ("youtube.com/@canal/live", "youtube", "https://youtube.com/@canal/live"),
    ("https://youtu.be/abcdefghijk", "youtube", "https://youtu.be/abcdefghijk"),
])
def test_resolve(alvo, plat, url):
    t = resolve(alvo)
    assert (t.platform, t.stream_url) == (plat, url)


def test_resolve_invalido():
    with pytest.raises(ValueError):
        resolve("https://example.com/x")


@pytest.mark.parametrize("url,vid", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/live/dQw4w9WgXcQ?si=x", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/@canal/live", None),
])
def test_video_id(url, vid):
    assert video_id_from_url(url) == vid


# ------------------------------------------------------------------- twitch
def test_parse_privmsg_mod():
    raw = ("@badges=moderator/1;display-name=Fulano;mod=1 "
           ":fulano!fulano@fulano.tmi.twitch.tv PRIVMSG #canal :!clip agora")
    m = parse_privmsg(raw, 1.0)
    assert (m.user, m.text, m.is_mod) == ("Fulano", "!clip agora", True)


def test_parse_privmsg_ignora_outros():
    assert parse_privmsg(":tmi.twitch.tv 001 justinfan :Welcome") is None


# ------------------------------------------------------------------ youtube
def _yt_msg(text_runs, badge=None, usec="1700000000000000"):
    r = {"message": {"runs": text_runs}, "authorName": {"simpleText": "Ana"},
         "timestampUsec": usec}
    if badge:
        r["authorBadges"] = [{"liveChatAuthorBadgeRenderer": {"icon": {"iconType": badge}}}]
    return {"addChatItemAction": {"item": {"liveChatTextMessageRenderer": r}}}


def test_youtube_parse_actions():
    data = {"continuationContents": {"liveChatContinuation": {
        "actions": [
            _yt_msg([{"text": "kkkkk "}, {"emoji": {"emojiId": "😂", "shortcuts": [":joy:"]}}]),
            _yt_msg([{"text": "!clip"}], badge="MODERATOR"),
            {"addLiveChatTickerItemAction": {}},
        ],
        "continuations": [{"invalidationContinuationData": {
            "continuation": "PROX", "timeoutMs": 2500}}],
    }}}
    msgs, nxt, wait = parse_actions(data)
    assert [m.text for m in msgs] == ["kkkkk 😂", "!clip"]
    assert [m.is_mod for m in msgs] == [False, True]
    assert msgs[0].ts == 1700000000.0
    assert (nxt, wait) == ("PROX", 2.5)


def test_youtube_fim_da_live():
    assert parse_actions({}) == ([], None, 1.0)


def test_youtube_initial_continuation():
    html = ('..."INNERTUBE_API_KEY":"KEY123","INNERTUBE_CLIENT_VERSION":"2.2024",...'
            '"continuations":[{"invalidationContinuationData":{"invalidationId":{"x":1},'
            '"timeoutMs":10000,"continuation":"CONT"}}]')
    assert initial_continuation(html) == ("KEY123", "2.2024", "CONT")


# ----------------------------------------------------------------- detector
def test_score_keywords_e_emojis():
    kw = DEFAULT_KEYWORDS
    assert message_score("oi", kw) == 1.0
    assert message_score("KEKW KEKW", kw) > message_score("kekw", kw)  # caixa alta
    assert message_score("kkkkkkkkkk", kw) == 2.5
    assert message_score("😂😂😂", kw) == 3.0


def test_detector_dispara_no_pico_e_respeita_intervalo():
    d = HypeDetector(window=10, threshold=2.5, min_score=15, cooldown=30, warmup=30)
    t = 0.0
    fired = []
    # 2 min de chat calmo: 1 msg a cada 2s
    while t < 120:
        if d.add(t, "oi gente"):
            fired.append(t)
        t += 2
    assert fired == []
    # explosão: 5 msgs/s com risada
    for i in range(50):
        r = d.add(t + i * 0.2, "KEKW KEKW")
        if r:
            fired.append(r)
    assert len(fired) == 1  # cooldown impede vários clipes do mesmo pico


def test_detector_aquecimento():
    d = HypeDetector(warmup=60, min_score=5)
    assert all(d.add(i * 0.1, "pog") is None for i in range(100))


# ------------------------------------------------- gravação + corte (ffmpeg)
def test_grava_e_corta(tmp_path: Path):
    src = tmp_path / "live.ts"
    subprocess.run([
        "ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440", "-t", "14",
        "-c:v", "libx264", "-g", "30", "-c:a", "aac", "-f", "mpegts", str(src),
    ], check=True)
    rec = Recorder(tmp_path / "buf", source=str(src), segment_seconds=1,
                   buffer_seconds=60, realtime_input=True)
    clipper = Clipper(rec, tmp_path / "clipes", pre_seconds=4, post_seconds=2)
    rec.start()
    try:
        time.sleep(7)
        out = clipper.clip(time.time(), "teste")
    finally:
        rec.stop()
    assert out and out.exists()
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True).stdout)
    assert 5 <= dur <= 9, dur
