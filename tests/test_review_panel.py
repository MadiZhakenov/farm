#!/usr/bin/env python3
"""
Отсмотр (ручная замена фона): «+ Ещё» и установка варианта проверяют
повтор в серии и пол так же, как автоподбор. Нужен дисплей (Xvfb в CI).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

pytest.importorskip("tkinter")
if not os.environ.get("DISPLAY") and sys.platform != "win32":
    pytest.skip("нет дисплея", allow_module_level=True)

import tkinter as tk  # noqa: E402

from core.carousel_rules import image_fingerprint  # noqa: E402
from core.harvester import CandidateImage  # noqa: E402
from tests.test_batch_integration import _img  # noqa: E402


def _make_run(tmp: Path) -> Path:
    run = tmp / "run_x"
    c1 = run / "carousel_001"
    (c1 / "alts").mkdir(parents=True)
    for n in (1, 2):
        _img(n).resize((1080, 1440)).save(c1 / f"{n}.jpg")
    _img(10).save(c1 / "alts" / "1_0.jpg")
    _img(11).save(c1 / "alts" / "1_1.jpg")  # это фото стоит в другой карусели
    _img(20).save(c1 / "alts" / "2_0.jpg")
    meta = {
        "topic": "night binge",
        "character_dna": {"gender": "female"},
        "slides": [
            {"index": 1, "text": "slide one", "query": "tea mug", "pin_id": "p10",
             "alt_pin_ids": ["p10", "p11"], "alt_pins": {"0": "p10", "1": "p11"}},
            {"index": 2, "text": "slide two", "query": "sky", "pin_id": "p20",
             "alt_pin_ids": ["p20"], "alt_pins": {"0": "p20"}},
        ],
    }
    (c1 / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return run


class FakeHarv:
    def __init__(self, cands):
        self.cands = cands
        self.exclude_seen: set[str] = set()

    def harvest_for_query(self, q, *, limit, exclude_ids, **kw):
        self.exclude_seen = set(exclude_ids)
        return [c for c in self.cands if c.pin_id not in exclude_ids], None

    def rank_review_alternatives(self, raw, *, limit, **kw):
        return raw[:limit]


@pytest.fixture()
def panel_env(tmp_path, monkeypatch):
    from core import photo_vault as pv
    import review_panel as rp

    vault = pv.PhotoVault(db_path=tmp_path / "v.db", thumbs_dir=tmp_path / "th")
    monkeypatch.setattr(pv, "_vault", vault)
    # фото alt 1_1 (другой pin!) уже стоит в чужой карусели
    vault.register_usage("OTHER/carousel_050", 3, pin_id="zzz", image=_img(11))
    vault.register_usage("OTHER/carousel_050", 4, pin_id="series-pin", image=_img(31))

    # пол: «мужское» фото — картинка с seed 32
    male_fp = image_fingerprint(_img(32))
    monkeypatch.setattr(
        rp, "_gender_clash",
        lambda image, gender, title="": gender == "female"
        and image_fingerprint(image) == male_fp,
    )
    asks: list[str] = []
    answer = {"v": False}

    def fake_ask(title, msg, **kw):
        asks.append(title)
        return answer["v"]

    monkeypatch.setattr(rp.messagebox, "askyesno", fake_ask)

    class SyncThread:  # поток «+ Ещё» выполняем сразу (в тесте нет mainloop)
        def __init__(self, target=None, daemon=None, **kw):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(rp.threading, "Thread", SyncThread)
    monkeypatch.setattr(rp.messagebox, "showerror", lambda *a, **k: None)
    monkeypatch.setattr(rp.messagebox, "showinfo", lambda *a, **k: None)

    run = _make_run(tmp_path)
    root = tk.Tk()
    root.withdraw()
    cands = []
    for pin, seed in (("series-pin", 31), ("male", 32), ("good1", 33), ("good2", 34)):
        c = CandidateImage(pin_id=pin, title="", source_url="", query="q", image=_img(seed))
        cands.append(c)
    harv = FakeHarv(cands)
    panel = rp.ReviewPanel(root, harvester=harv)
    panel.load_run(run)
    yield panel, root, run, vault, asks, answer, harv
    root.destroy()


def _wait(panel, root, timeout=20):
    t0 = time.time()
    while panel._fetch_busy and time.time() - t0 < timeout:
        root.update()
        time.sleep(0.05)
    root.update()


def test_fetch_more_skips_series_and_gender(panel_env):
    panel, root, run, vault, asks, answer, harv = panel_env
    panel._popover_ctx = {"row_idx": 0, "slide_idx": 0, "slide_n": 1}
    panel._query_var.set("tea mug window")
    panel._fetch_more_alts(replace_query=False)
    _wait(panel, root)
    meta = json.loads((run / "carousel_001" / "meta.json").read_text(encoding="utf-8"))
    saved = set(meta["slides"][0]["alt_pins"].values())
    assert "good1" in saved and "good2" in saved
    assert "series-pin" not in saved, "фото из другой карусели не предлагается"
    assert "male" not in saved, "фото другого пола не предлагается"
    # поиск сразу не берёт занятые pin и фото других слайдов этой карусели
    assert "series-pin" in harv.exclude_seen and "p20" in harv.exclude_seen


def test_apply_alt_asks_before_reusing_series_photo(panel_env):
    panel, root, run, vault, asks, answer, harv = panel_env
    slide = run / "carousel_001" / "1.jpg"
    before = slide.read_bytes()
    alt = run / "carousel_001" / "alts" / "1_1.jpg"

    answer["v"] = False
    panel._apply_alt(0, 0, 1, alt)
    assert asks == ["Фото уже используется"]
    assert slide.read_bytes() == before, "отказ — слайд не меняется"

    answer["v"] = True
    panel._apply_alt(0, 0, 1, alt)
    assert slide.read_bytes() != before
    meta = json.loads((run / "carousel_001" / "meta.json").read_text(encoding="utf-8"))
    assert meta["slides"][0]["pin_id"] == "p11"
    key = str((run / "carousel_001").resolve())
    with vault._connect() as conn:
        row = conn.execute(
            "SELECT pin_id FROM used_photos WHERE carousel=? AND slide=1", (key,)
        ).fetchone()
    assert row["pin_id"] == "p11", "ручная замена записана в учёт серии"


def test_apply_own_previous_photo_does_not_nag(panel_env):
    panel, root, run, vault, asks, answer, harv = panel_env
    # своё же прежнее фото слайда (p10) — без вопросов
    panel._apply_alt(0, 0, 0, run / "carousel_001" / "alts" / "1_0.jpg")
    assert asks == []


def test_apply_alt_gender_clash_asks(panel_env):
    panel, root, run, vault, asks, answer, harv = panel_env
    male = run / "carousel_001" / "alts" / "1_5.jpg"
    _img(32).save(male)
    answer["v"] = False
    panel._apply_alt(0, 0, 5, male)
    assert asks == ["Другой пол"]
