#!/usr/bin/env python3
"""
Drops react — запись геймплея игр с drops.game (витрина, без входа) для роликов: Playwright + установленный Edge,
мобильный экран 430×932 при DSF 2.5 → кадры CDP-скринкаста ~1075×2330 (видео Playwright пишет только в CSS-px).
«Игрок» жмёт стрелки/пробел со случайным ритмом. Нужны разные вариации (геймплей пойдёт и в следующие ролики):
каждый запуск — свой сид.

  python record_drops_gameplay.py --game 17bd5eb4-dedc-44c7-95f3-824c3bac4e7e --secs 25 --seed 1
  python record_drops_gameplay.py --all --secs 30 --seed 2
→ output/drops_react/gameplay/<игра>_<сид>.mp4 (30 fps, без звука)
"""

from __future__ import annotations

import argparse
import base64
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output" / "drops_react" / "gameplay"
GAMES = {
    "17bd5eb4-dedc-44c7-95f3-824c3bac4e7e": "runner_forest",
    "0ae512db-7797-46f8-93d6-98afab282d53": "flight_meltdown",
    "53b485c2-938b-4b9f-92c2-6d66f362b405": "obby",
    "d550b193-aff1-45d5-b409-7d387f424ac9": "platformer_rooftop",
    "4ccb2c35-e9c6-452b-9374-f33c169b24a3": "drift_graveyard",
    "6b76a012-4b5e-4a08-9bd7-c1f5eae63ea1": "rhythm_dock",
    "469a3ce4-0f1d-460f-b52a-660386b79ed4": "shooter_partypop",      # наша игра (Drops react / drops3), Kulakovka
    "a3b6300b-9a0a-4b31-8deb-3b96c1198dc7": "shooter_ariavale",      # та же игра заново, артист Aria Vale
}
VW, VH, DSF = 430, 932, 2.5


class Recorder:
    """CDP Page.startScreencast: каждый кадр — JPEG в папку + время прихода; потом склейка с длительностями."""

    def __init__(self, page, folder: Path):
        self.dir, self.n, self.t = folder, 0, []
        folder.mkdir(parents=True, exist_ok=True)
        self.cdp = page.context.new_cdp_session(page)
        self.cdp.on("Page.screencastFrame", self.frame)

    def frame(self, ev) -> None:
        (self.dir / f"{self.n:05d}.jpg").write_bytes(base64.b64decode(ev["data"]))
        self.t.append(time.perf_counter())
        self.n += 1
        try:
            self.cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
        except Exception:
            pass

    def start(self) -> None:
        self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 82, "maxWidth": 1400,
                                               "maxHeight": 2600, "everyNthFrame": 1})

    def stop(self) -> None:
        self.cdp.send("Page.stopScreencast")

    def save(self, dst: Path) -> None:
        lst = self.dir / "list.txt"
        lines = []
        for i in range(self.n):
            dur = (self.t[i + 1] - self.t[i]) if i + 1 < self.n else 1 / 30
            lines += [f"file '{(self.dir / f'{i:05d}.jpg').as_posix()}'", f"duration {max(dur, 1 / 120):.4f}"]
        lines.append(f"file '{(self.dir / f'{self.n - 1:05d}.jpg').as_posix()}'")
        lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-vf", "fps=30,scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p", "-c:v", "h264_nvenc",
                        "-preset", "p5", "-cq", "19", "-map_metadata", "-1", str(dst)], check=True)


def click_play(page) -> None:
    """«Play» — кнопка в кадре движка (playmusic.gg/engine); точное имя, иначе можно попасть в «Play together»
    (открывает комнату вместо игры)."""
    for _ in range(30):
        for fr in page.frames:
            if "engine" not in fr.url:
                continue
            try:
                loc = fr.get_by_role("button", name="Play", exact=True)
                if loc.count() and loc.first.is_visible():
                    loc.first.click(timeout=1500)
                    return
            except Exception:
                continue
        page.wait_for_timeout(500)


def play(page, secs: float, rng: random.Random) -> None:
    """Ожидания — через page.wait_for_timeout: sync-Playwright разбирает события (кадры скринкаста) только внутри
    своих вызовов, time.sleep останавливал скринкаст (~10 кадров/с вместо 60)."""
    keys = ["ArrowLeft", "ArrowRight", "ArrowUp", "Space", "ArrowDown", "ArrowUp", "Space"]
    if any(g in page.url for g in ("469a3ce4", "a3b6300b")):           # шутер: только смена полос
        keys = ["ArrowLeft", "ArrowRight"]
    t_end = time.time() + secs
    while time.time() < t_end:
        k = rng.choice(keys)
        page.keyboard.down(k)
        page.wait_for_timeout(rng.uniform(50, 250))
        page.keyboard.up(k)
        page.wait_for_timeout(rng.uniform(200, 800))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", default="17bd5eb4-dedc-44c7-95f3-824c3bac4e7e")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--secs", type=float, default=25)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--headed", action="store_true", help="окно видно (отладка)")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    games = list(GAMES) if a.all else [a.game]
    with sync_playwright() as pw:
        # настоящий DSF (флаг Chromium), а не эмуляция Playwright — только так скринкаст отдаёт кадры в device-px
        br = pw.chromium.launch(channel="msedge", headless=not a.headed,
                                args=["--autoplay-policy=no-user-gesture-required", f"--force-device-scale-factor={DSF}",
                                      f"--window-size={VW},{VH}", "--use-angle=d3d11", "--ignore-gpu-blocklist", "--force_high_performance_gpu",
                                      "--enable-gpu-rasterization", "--disable-frame-rate-limit"])
        for gid in games:
            rng = random.Random(a.seed * 1000 + sum(map(ord, gid)))
            ctx = br.new_context(no_viewport=True)
            page = ctx.new_page()
            page.goto(f"https://drops.game/play/{gid}", wait_until="domcontentloaded")
            rec = Recorder(page, OUT / "_frames")
            time.sleep(6)                                         # загрузка игры
            click_play(page)
            time.sleep(1.0)
            try:
                page.locator("iframe").first.click(timeout=2000)  # фокус в игру — клавиши идут в неё
            except Exception:
                page.mouse.click(200, 400)
            rec.start()
            play(page, a.secs, rng)
            rec.stop()
            ctx.close()
            dst = OUT / f"{GAMES.get(gid, gid[:8])}_{a.seed}.mp4"
            rec.save(dst)
            shutil.rmtree(OUT / "_frames", ignore_errors=True)
            print(dst.name, rec.n, "кадров", flush=True)
        br.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
