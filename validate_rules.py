#!/usr/bin/env python3
"""
Проверка новых правил на НАСТОЯЩИХ фото (SigLIP, как в фабрике).

Прогоняет все слайды пачки (по умолчанию ../06_food_body_image) через SigLIP и
сохраняет сырые сходства картинок с текстовыми якорями («грязь», «чисто»,
«кухня», «кровать»…) + эмбеддинги. По этим данным подбираются пороги
CALIBRATION в core/carousel_rules.py.

Ничего в проекте не меняет. Результат:
  out/validation/rules_validation.json
  out/validation/rules_validation.npz

Запуск:  python validate_rules.py [папка_с_слайдами]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Якоря: основные (как в core/carousel_rules.py) + запасные для подбора
PROMPTS: dict[str, list[str]] = {
    "mess": [
        "dirty dishes piled in a kitchen sink",
        "a dirty plate with food leftovers and crumbs",
        "trash, garbage and food wrappers everywhere",
        "a messy cluttered kitchen counter with dirty dishes",
        "spilled coffee or a spilled drink on a table",
        "a pile of junk food bags and candy wrappers",
        "an overflowing trash can",
        "a dirty greasy stove with used pans",
        # запасные
        "a disgusting dirty kitchen",
        "unwashed dishes and food waste",
        "a messy room with clutter everywhere",
        "crumbs and stains on a table",
        "empty snack wrappers and packaging",
        "a dirty sink",
        "a knocked over cup with spilled coffee on a desk",
        "a puddle of spilled coffee next to a laptop",
        "a coffee stain and spilled liquid on a table",
    ],
    "clean": [
        "a clean tidy table",
        "a calm cozy room",
        "a cup of tea by a window",
        "a person walking outside",
        "a neat clean kitchen",
        "fresh food on a clean plate",
        "a city street",
        "an open fridge with food inside",
        "a bed with white sheets",
        "a desk with a laptop and notebook",
        # запасные
        "a pleasant aesthetic photo",
        "a beautiful calm scene",
        "healthy fresh food",
        "a person in a room",
    ],
    "place_kitchen": [
        "a kitchen", "an open fridge", "a kitchen counter",
        "a pantry shelf with food", "a kitchen sink", "a stove with pans",
    ],
    "place_bed": ["a bed with sheets and pillows", "a bedroom", "lying in bed"],
    "place_desk": [
        "a desk with a laptop", "a work desk with papers", "a study desk with notebooks",
    ],
    "place_bathroom": ["a bathroom", "a bathroom mirror and sink"],
    "place_street": ["a city street", "a sidewalk outdoors", "a park outdoors"],
    "place_car": ["inside a car", "a view from a bus window"],
    "place_cafe": ["a cafe table", "a restaurant table"],
    "place_food": ["a close-up of food", "snacks on a surface"],
    "place_other": ["a photo of an object", "a hallway", "the sky"],
    "gender": ["a woman, a girl", "a man, a guy"],
    "person": [
        "a person visible in frame, human body hair face hands silhouette",
        "empty room objects only still life interior no people no human",
    ],
}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "06_food_body_image"
    files = sorted(p for p in src.glob("*.jpg"))
    if not files:
        print(f"Нет картинок в {src}")
        return 1
    print(f"Картинок: {len(files)} из {src}")

    from core.taste_embedder import get_embedder

    from core.taste_embedder import SIGLIP_ID

    t0 = time.perf_counter()
    emb = get_embedder()
    try:
        backend = emb.ensure(SIGLIP_ID)  # фабрика работает на SigLIP — проверяем его
    except Exception as exc:
        print(f"\nSigLIP не загрузился: {type(exc).__name__}: {exc}")
        print("Запусти install.bat (поставит sentencepiece) и повтори проверку.")
        return 2
    print(f"Модель: {backend} на {emb.device} ({time.perf_counter() - t0:.0f} с)")

    names: list[str] = []
    for group, texts in PROMPTS.items():
        for t in texts:
            names.append(f"{group}::{t}")
    all_texts = [n.split("::", 1)[1] for n in names]
    t_mat = emb.embed_texts(all_texts)

    vecs = []
    batch = 16
    for i in range(0, len(files), batch):
        ims = [Image.open(p).convert("RGB") for p in files[i : i + batch]]
        vecs.append(emb.embed_images(ims))
        for im in ims:
            im.close()
        print(f"  {min(i + batch, len(files))}/{len(files)}", flush=True)
    i_mat = np.concatenate(vecs, axis=0)
    sims = i_mat @ t_mat.T

    scale = getattr(emb._model, "logit_scale", None)
    bias = getattr(emb._model, "logit_bias", None)
    try:
        scale_v = float(scale.exp().detach().cpu().item()) if scale is not None else None
    except Exception:
        scale_v = None
    try:
        bias_v = float(bias.detach().cpu().item()) if bias is not None else None
    except Exception:
        bias_v = None

    out_dir = ROOT / "out" / "validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out_dir / "rules_validation.npz",
        image_emb=i_mat.astype(np.float16),
        text_emb=t_mat.astype(np.float16),
        sims=sims.astype(np.float32),
    )
    payload = {
        "backend": backend,
        "device": str(emb.device),
        "logit_scale_exp": scale_v,
        "logit_bias": bias_v,
        "files": [p.name for p in files],
        "prompts": names,
        "sims": [[round(float(x), 5) for x in row] for row in sims],
        "seconds": round(time.perf_counter() - t0, 1),
    }
    (out_dir / "rules_validation.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nГотово за {payload['seconds']} с -> {out_dir}")
    print("Можно закрыть окно и написать Claude, что проверка прошла.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
