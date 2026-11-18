#!/usr/bin/env python3
"""
OneState KO «графика» (ID 1) — 200 TikTok + 200 YouTube, схожесть 0–1 % для худшей пары (юзер 16.11, ночная очередь).
Формат рефа (drive 1FEuOV3v… = формат 1309): белый фон, короткая подпись сверху (4 текста ТЗ дословно, корейский) →
геймплей посередине → реальный корейский комментарий снизу (карточка X, 4 текста ТЗ дословно, все про такси) +
баннер промокода STATEDQVH (KO), логотип. Акцент — графика 1.3 / «это игра на телефоне?»: облёты городов Map Update
(Compton, Countryside, Santa Monica), механик, такси (комментарии про такси). Без стрельбы по игрокам и поверженных
персонажей. 9:16, 15 с. Музыка — официальная (звук роликов Map Update), тихо (−18 LUFS), со своим отрезком у ролика.

Уникальность и проверка — как OneState 5: план по прогнозу отпечатков (core/uniq_fast), приёмка настоящего файла по
КАЖДОМУ кадру (порог с запасом), bad_frames + frame_check (каждый кадр = кадр исходника по плану), в конце
check_uniq_allframes по всем парам. Видеокарта: cuvid -crop -resize → кадры в памяти → склейка → overlay в памяти → NVENC.

  python build_onestate_ko.py --test                       # 4 тестовых (по одному на комментарий) → output/_work/onestate_ko_gfx/test
  python build_onestate_ko.py --tt 200 --yt 200 --jobs 3   # → output/onestate_ko_gfx_TT_200 + _YT_200
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core import gpu_ffmpeg as G  # noqa: E402
from core.uniq_check import hashes, vhash  # noqa: E402
from core import uniq_fast as UF  # noqa: E402

ID, NAME = "1", "onestate_ko_gfx"
W, H, FPS, TOTAL = 1080, 1920, 30, 15.0
NF = round(TOTAL * FPS)
Q = 8                                                  # масштаб расчёта до рендера (кадр 135×240)
CW, CH = 240, 135                                      # кэш исходников: серые 240×135, 30 к/с
STRIP = (450, 930)                                     # полоса проверки (только геймплей) — как OneState 4 v3 / 1310_v2
HFPS, THR, PLAN_THR = 6, 40, 52
SHADE_AMP = 0.10
SP = "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv"
WORK = ROOT / "output" / "_work" / "onestate_ko_gfx"
SEGD = WORK / "seg"
FONT = {"tt": "tiktok", "yt": "default"}
D1309 = ROOT / "downloads" / "1309" / "scenes"
OS3 = ROOT / "downloads" / "onestate3" / "src"         # записи 2560×1440 30 к/с (запас по зуму)
MATS = ROOT / "downloads" / "os_ko_gfx" / "materials" / "1.00 (Global Launch)"
MU = MATS / "New Locations" / "Horizontal videos"
MECH = MATS / "Mechanic (New profession)" / "Mechanics-001.mp4"
KO_BANNER = ROOT / "downloads" / "os_ko_gfx" / "banner" / "OneState_PromoBanner_V2_Loop_NoAmount_KO_04_STATEDQVH.mov"
MU_FILES = {"c": "OS_VP_Map_Update_Compton_1920x1080", "y": "OS_VP_Map_Update_Countryside_1920x1080",
            "s": "OS_VP_Map_Update_Santa_Monica_1920x1080_48s"}
MUSICS = [WORK / f"music_{k}.wav" for k in MU_FILES]          # официальная музыка OneState (звук роликов Map Update)
FONT_KO_B, FONT_KO = Path(r"C:\Windows\Fonts\malgunbd.ttf"), Path(r"C:\Windows\Fonts\malgun.ttf")
BANNER_T = 1.0
OV = "cpu"                                             # слои: gpu (overlay_cuda) | cpu (overlay в памяти)
DEC = "cuvid"                                          # распаковка кусков: cuvid | cuvid32 | nvdec (см. --dec)
# прошлые партии OneState в той же раскладке/с тем же футажом — с ними тоже 0 общих кадров
# прошлые партии, где был тот же исходник (такси Taxi_job_1 — OneState 3/4/5, mic). 1309/1310 сняты с других записей
# (сцены 1309), общих кадров с KO быть не может — в сравнении они только раздували банк (приёмка ползла).
REFS = ["onestate_4_TT_200", "onestate_4_YT_200", "onestate_3_TT_100", "onestate_3_YT_200",
        "onestate_5_TT_200", "onestate_5_YT_200", "onestate_mic_TT_200", "onestate_mic_YT_200"]

# ТЗ дословно (переносы по смыслу)
CAPTIONS_KO = [
    ["이 정도면 폰 안에", "도시 하나 넣어둔 거 아님? 🤯"],
    ["아니 물 반사까지", "구현한 거 실화냐 👀🔥"],
    ["폰겜 그래픽", "언제 여기까지 온 거임?"],
    ["잠깐 이게 폰겜이라고?ㅋㅋ"],
]
COMMENTS_KO = [
    ["택시 첫 손님이 경찰한테 쫓기는 중이었음.", "난 목적지 물어봤는데 일단 밟으래ㅋㅋ 💀"],
    ["친구가 택시 시작했다길래 손님인 척 탔는데", "길을 몰라서 내가 운전함ㅋㅋ", "돈은 왜 내가 내냐 😭"],
    ["택시 손님이 잠깐만 기다려 달래서 기다렸는데", "다른 차 타고 감ㅋㅋ 게임에서도 이러네 🫠"],
    ["택시 운전하다가 손님 연애 상담만 한 시간 해줌ㅋㅋ", "목적지는 도착했는데 얘기가 안 끝나 😭"],
]
COMMENTS_RAW = [" ".join(c) for c in COMMENTS_KO]
KIND = ["taxi"] * len(COMMENTS_KO)
PEOPLE_KO = [  # выдуманные корейские комментаторы (имя, ник) — как у обычных людей в X
    ("민지", "minji_0412"), ("준호", "junho.kim97"), ("서연 🌙", "seoyeon__"), ("지훈", "jihoon_p"), ("하은", "haeun.lee"),
    ("도윤", "doyun0821"), ("수아 🍓", "sua_xx"), ("현우", "hyunwoo_c"), ("예린", "yerin.o_o"), ("태민", "taemin_33"),
    ("지수", "jisoo.kwon"), ("민재 🎮", "minjae_gg"), ("다은", "daeun__s"), ("승현", "seunghyun_k"), ("유나", "yuna.park"),
    ("재원", "jaewon_94"), ("소희", "sohee_xo"), ("건우", "geonwoo.j"), ("채원 ✨", "chaewon_1004"), ("동현", "donghyun.y"),
    ("나연", "nayeon__l"), ("성민", "sungmin_08"), ("은지", "eunji.h"), ("우진", "woojin_kr"), ("가은", "gaeun.c"),
    ("준서", "junseo_22"), ("하린", "harin_s2"), ("시우", "siwoo.l"), ("혜원", "hyewon__"), ("정우", "jungwoo_m"),
    ("수빈 🐰", "subin.k"), ("민혁", "minhyuk_01"), ("지민", "jimin.o"), ("연우", "yeonwoo__"), ("서진", "seojin_park"),
    ("유진", "yujin.c"), ("상우", "sangwoo_77"), ("다현", "dahyun_s"), ("규민", "gyumin.j"), ("아린", "arin_xo"),
]

# ---------------- куски исходников (внутри одного шота) ----------------
# (ключ, файл, начало, конец, место, правило кадра): mid — кино/сцена по центру; hud — геймплей с интерфейсом сверху:
# окно ниже середины (машина внизу кадра), зум больше
SPANS = {
    # такси (Taxi_job_1: кино 0.15–2.35 / 13.9–15.35 / 15.45–17.1, геймплей 2.5–13.75 / 17.2–27.75 — OneState 3)
    "tx_k1": ("os3", "Taxi_job_1", 0.15, 2.35, "taxi_k1", "mid"),
    "tx_k2": ("os3", "Taxi_job_1", 13.9, 15.35, "taxi_k2", "mid"),
    "tx_k3": ("os3", "Taxi_job_1", 15.45, 17.1, "taxi_k3", "mid"),
    "tx_g1": ("os3", "Taxi_job_1", 2.5, 13.75, "taxi_g1", "hud"),
    "tx_g2": ("os3", "Taxi_job_1", 17.2, 27.75, "taxi_g2", "hud"),
}
TAXI = ["tx_k1", "tx_k2", "tx_k3", "tx_g1", "tx_g2"]
MAPU, MECHS = [], []
# 17.11 клиент: «все ролики с движения человека начинались» → первый кусок — только план, где весь кусок в кадре
# двигается человек (механик идёт к машине / садится у колеса / лезет под капот; mc_07 — прохожий идёт по дорожке).
# Отобрано по листам кадров всех 73 кусков (остальные: облёты, машины, такси, экран «Job Results», кодовый замок).
HUMAN = ["me_005", "me_006", "me_008", "me_010", "me_015", "me_017", "me_018", "me_019", "me_020", "me_041", "me_042",
         "me_043", "me_044", "me_045", "me_047", "me_048", "me_049", "me_051", "me_052", "me_053", "me_054", "mc_07"]
OPEN_START = 0.5                         # движение в окне в первые 10 кадров (средняя разница соседних, уровни серого)
# (доля движения «внутри окна» не работает: камера игры сама ведёт персонажа — движение по всему кадру ≈ площади окна,
#  замер 17.11; человек в кадре держится тем, что камера держит его у центра, а окно первого куска — у центра)


def _load_spans() -> None:
    """Планы роликов Map Update (резка по жёстким склейкам, output/_work/os_ko_gfx/scenes.json): без заставки
    «MAP UPDATE» (первый план) и логотипа (последний), ≥ 1.7 с, по 0.1 с от склеек. Механик — планы ≥ 2.6 с без
    повторов кадров (scenes_mech.json), не длиннее 9 с."""
    sj = ROOT / "output" / "_work" / "os_ko_gfx" / "scenes3.json"     # v3: склейки + шторки/наплывы вырезаны (±10 кадров)
    sc = json.loads(sj.read_text(encoding="utf-8"))
    for key, name in MU_FILES.items():
        for i, x in enumerate(sc[name]):
            if x["dur"] >= 1.7:
                k = f"m{key}_{i:02d}"
                SPANS[k] = ("mu", name, x["s"], x["e"], k, "air")
                MAPU.append(k)
    mj = ROOT / "output" / "_work" / "os_ko_gfx" / "scenes_mech.json"
    if mj.exists():
        for i, x in enumerate(json.loads(mj.read_text(encoding="utf-8"))["shots"]):
            if x["dur"] >= 2.6 and x["dups"] == 0:
                k = f"me_{i:03d}"
                SPANS[k] = ("mech", "Mechanics-001", round(x["s"] + 0.1, 3), round(min(x["e"], x["s"] + 9.0) - 0.1, 3), k,
                            "hud")
                MECHS.append(k)


_load_spans()


def src_path(kind: str, name: str) -> Path:
    return {"1309": D1309 / f"{name}.mp4", "os3": OS3 / f"{name}.mp4", "mu": MU / f"{name}.mp4", "mech": MECH}[kind]


SEG: dict = {}        # ключ → dict(path, sw, sh, n, bad: set кадров-повторов)
SRC: dict = {}        # ключ → кадры 240×135
TABLE: dict = {}      # шрифт → {номер комментария: высота карточки}
PROG = ROOT / "output" / "_work" / "_qa_progress" / f"{os.getpid()}.json"     # дашборд localhost:8767 («Сейчас идёт»)


def prog(stage: str, done: int = 0, total: int | None = None) -> None:
    """Что делает сборщик сейчас — для дашборда (этап, сделано, всего)."""
    try:
        PROG.parent.mkdir(parents=True, exist_ok=True)
        PROG.write_text(json.dumps(dict(stage=stage, done=done, total=total), ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def vname(job: dict) -> str:
    return f"{NAME}_{job['tag']}_{job['n']:03d}_{ID}.mp4"


# ---------------- воркеры (шрифт задаётся ДО импорта build_1309_*: TT — TikTok Sans, YT — шрифты 1309) ----------------
_M: dict = {}


def _init_font(font: str) -> None:
    os.environ["OS1309_FONT"] = font
    import build_1309_dance_reels as DR
    B = DR.B
    from PIL import ImageFont
    B.F_CAP = B.F_MED = B.F_BOLD = FONT_KO_B             # корейский: Malgun Gothic (в Figtree/Inter/TikTok Sans нет хангыля)
    B.F_REG = FONT_KO
    B.font = lambda path, px: ImageFont.truetype(str(path), px)
    B.CAPTIONS, B.COMMENTS, B.PEOPLE = CAPTIONS_KO, COMMENTS_KO, PEOPLE_KO
    B.BANNER_ANIM = WORK / "banner_ko_anim.mov"
    _M.update(B=B, DR=DR)


def _table() -> dict:
    import tempfile
    B = _M["B"]
    tmp = Path(tempfile.mkdtemp(prefix="os5t_"))
    av = next(p for d in B.AVATAR_DIRS if d.is_dir() for p in sorted(d.glob("*.jpg")))
    out = {str(k): B.card_png(k, tuple(B.PEOPLE[0]), av, tmp / "k.png") for k in range(len(COMMENTS_RAW))}
    out["lines"] = {str(k): len(B.COMMENTS[k]) for k in range(len(COMMENTS_RAW))}
    out["cap"] = {str(k): B.caption_png(k, tmp / "c.png") for k in range(len(CAPTIONS_KO))}
    shutil.rmtree(tmp, ignore_errors=True)
    out["card_bottom"] = B.CARD_BOTTOM
    return out


def cap_of(tag: str, n: int) -> int:
    """Подпись сверху: по кругу, у YT со сдвигом — все 16 сочетаний подпись × комментарий."""
    return ((n - 1) // len(COMMENTS_KO) + (0 if tag == "tt" else 1)) % len(CAPTIONS_KO)


def layout(rng: random.Random, tag: str, comment: int, cap: int = 0) -> dict | None:
    """Полоса геймплея (верх b0, высота bh) и карточка под ней; блок примерно по центру. Полоса закрывает STRIP
    целиком, промокод и логотип (низ полосы) — ниже STRIP."""
    T = TABLE[FONT[tag]]
    ch = T[str(comment)]
    cb = T["cap"][str(cap)]
    for _ in range(40):
        b0 = cb + rng.randint(26, 50)
        b0 -= b0 % 2
        gap = rng.randint(26, 46)
        lift = rng.randint(0, 60)
        card_top = T["card_bottom"] - lift - ch
        bh = card_top - gap - b0
        bh -= bh % 2
        if b0 <= STRIP[0] - 10 and b0 + bh >= 1110 and bh >= 680:
            return dict(b0=b0, bh=bh, gap=gap, card_lift=lift, card_top=card_top, cap=cap, cap_bottom=cb)
    return None


def src_rect(p: dict, bh: int) -> tuple[float, float, float, float]:
    """Окно исходника: «заполнить полосу» с зумом z, положение ox/oy (0.5 — центр)."""
    sw, sh = SEG[p["k"]]["sw"], SEG[p["k"]]["sh"]
    s = max(W * p["z"] / sw, bh * p["z"] / sh)
    cw, ch = min(sw, W / s), min(sh, bh / s)            # z = 1.0: округление давало окно на 1e-13 шире кадра
    return max(0.0, (sw - cw) * p["ox"]), max(0.0, (sh - ch) * p["oy"]), cw, ch


def shade_field(seed: int, w: int, h: int) -> np.ndarray:
    """Мягкие волны освещения (как Skinive 2 / OneState 4): v<0 — светлее, v>0 — темнее, сила |v|·AMP."""
    rng = random.Random(seed)
    x = np.linspace(0, 1, w, dtype=np.float32)[None, :]
    y = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    ph = (rng.uniform(0, 6.28) + y * rng.uniform(-6, 6)
          + np.sin(y * rng.uniform(2, 5) + rng.uniform(0, 6.28)) * rng.uniform(0.5, 1.5))
    return (0.6 * np.sin(2 * math.pi * rng.uniform(1.2, 2.6) * x + ph)
            + 0.4 * np.sin(2 * math.pi * rng.uniform(2.5, 4.5) * x + ph * 1.7 + rng.uniform(0, 6.28)))


# ---------------- рендер (видеокарта) ----------------
class _Res:
    def __init__(self, code: int, err: str):
        self.returncode, self.stderr = code, err


def _run_ff(cmd: list, errf: Path, timeout: float = 120) -> _Res:
    """ffmpeg без каналов (stderr в файл): зависшую сборку на видеокарте прерываем."""
    with open(errf, "w", encoding="utf-8", errors="replace") as fe:
        pr = subprocess.Popen(cmd[:1] + ["-nostdin"] + cmd[1:], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=fe)
        try:
            code = pr.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pr.kill()
            try:
                pr.wait(timeout=15)
            except subprocess.TimeoutExpired:
                pass
            code = -9
    err = errf.read_text(encoding="utf-8", errors="replace")
    return _Res(code, err + (chr(10) + f"timeout {timeout:.0f} s" if code == -9 else ""))


def build(job: dict) -> str:
    import tempfile
    from core.gpu_slots import gpu_slot
    B = _M["B"]
    SEG.update(job["segs"])
    tmp = Path(tempfile.mkdtemp(prefix="os5_"))
    rng = random.Random(job["seed"])
    b0, bh, card_top = job["b0"], job["bh"], job["card_top"]
    card_h = B.card_png(job["comment"], tuple(job["person"]), Path(job["avatar"]), tmp / "card.png")
    if B.CARD_BOTTOM - job["card_lift"] - card_h != card_top:
        raise RuntimeError(f"{vname(job)}: карточка {card_h} не совпала с планом")
    bgv, tint = job["bg"], job["tint"]
    bgc = f"0x{bgv:02X}{min(255, bgv + tint):02X}{min(255, bgv - tint):02X}"
    lx, ly, _ = B.logo_png(rng, (b0, b0 + bh), tmp / "logo.png")
    v = shade_field(job["shade"], W, H)[b0:b0 + bh]
    lay = np.zeros((H, W, 4), np.uint8)
    lay[b0:b0 + bh, :, :3] = np.where(v < 0, 255, 0)[..., None]
    lay[b0:b0 + bh, :, 3] = (np.abs(v) * SHADE_AMP * 255).astype(np.uint8)
    layer = Image.fromarray(lay, "RGBA")
    layer.alpha_composite(Image.open(tmp / "logo.png").convert("RGBA"), (lx, ly))
    layer.alpha_composite(Image.open(tmp / "card.png").convert("RGBA"), (0, card_top))
    if B.caption_png(job["cap"], tmp / "cap.png") != job["cap_bottom"]:
        raise RuntimeError(f"{vname(job)}: подпись не совпала с планом")
    layer.alpha_composite(Image.open(tmp / "cap.png").convert("RGBA"), (0, 0))
    layer.save(tmp / "layer.png", compress_level=1)
    cw_, ch_ = B.banner_anim()
    bx = G._even((W - cw_) // 2)
    by = G._even(b0 + bh - 16 - ch_ + round(ch_ * 0.06))
    ins = ["-i", str(tmp / "layer.png"), "-i", str(B.BANNER_ANIM), "-ss", f"{job['moff']:.2f}", "-i", str(MUSICS[job["mus"]]),
           "-f", "lavfi", "-i", f"color=c={bgc}:s={W}x{H}:r={FPS}:d={TOTAL}"]
    ov = os.environ.get("OS5_OV", OV)
    if ov == "gpu":
        fc = [G.layer(0, 0, NF, "ly", FPS).replace("format=yuva420p,hwupload_cuda", f"format=yuva420p,{SP},hwupload_cuda"),
              f"[1:v]fps={FPS},format=yuva420p,{SP},hwupload_cuda,setpts=PTS-STARTPTS+{BANNER_T:.3f}/TB[bn]",
              f"[3:v]format=yuv420p,{SP},hwupload_cuda[c]"]
    else:                                                 # слои — обычным overlay в памяти, NVENC берёт готовый кадр
        fc = [f"[0:v]loop=loop={NF - 1}:size=1:start=0,settb=1/{FPS},setpts=N,format=yuva420p[ly]",
              f"[1:v]fps={FPS},format=yuva420p,setpts=PTS-STARTPTS+{BANNER_T:.3f}/TB[bn]",
              "[3:v]format=yuv420p[c]"]
    for j, p in enumerate(job["pieces"]):
        x, y, cw, ch = (G._even(t) for t in src_rect(p, bh))
        sg = SEG[p["k"]]
        mode = os.environ.get("OS5_DEC", DEC)
        if mode == "cpu":                                 # эталон: распаковка процессором
            ins += ["-i", sg["path"]]
            geo_f = f"crop={cw}:{ch}:{x}:{y},scale={W}:{bh}:flags=bicubic,"
        elif mode == "nvdec":                               # распаковка nvdec → кадр в обычную память, обрезка/масштаб — процессор
            ins += ["-hwaccel", "cuda", "-i", sg["path"]]
            geo_f = f"crop={cw}:{ch}:{x}:{y},scale={W}:{bh}:flags=bicubic,"
        else:                                             # h264_cuvid режет и масштабирует сам
            # распаковка С НУЖНОГО МЕСТА (-ss до -i: ближайший ключевой кадр заготовки, их каждые 15, лишнее отбрасывается
            # точно по времени) — иначе распаковщик гонит кусок с начала заготовки (замер 16.11: NVDEC 96 %, половина впустую)
            ss = ["-ss", f"{(p['f0'] - 0.5) / FPS:.4f}"] if p["f0"] > 0 else []
            ins += ["-c:v", "h264_cuvid", *(["-surfaces", "32"] if mode == "cuvid32" else ["-surfaces", "8"] if mode == "cuvid8" else []),
                    "-crop", f"{y}x{sg['sh'] - y - ch}x{x}x{sg['sw'] - x - cw}", "-resize", f"{W}x{bh}", *ss, "-i", sg["path"]]
            geo_f = ""
        f0 = 0 if mode not in ("cpu", "nvdec") else p["f0"]
        fc.append(f"[{4 + j}:v]trim=start_frame={f0}:end_frame={f0 + p['frames']},setpts=PTS-STARTPTS,"
                  f"{geo_f}setsar=1,format=yuv420p,tpad=stop_mode=clone:stop=3,trim=end_frame={p['frames']},"
                  f"setpts=PTS-STARTPTS[p{j}]")
    n = len(job["pieces"])
    if ov == "gpu":
        fc += ["".join(f"[p{j}]" for j in range(n)) + f"concat=n={n}:v=1:a=0,{SP},hwupload_cuda[g]",
               f"[c][g]overlay_cuda=0:{b0}[gg]",
               "[gg][ly]overlay_cuda=0:0[d]",
               f"[d][bn]overlay_cuda={bx}:{by}:eof_action=pass[v]"]
    else:
        fc += ["".join(f"[p{j}]" for j in range(n)) + f"concat=n={n}:v=1:a=0[g]",
               f"[c][g]overlay=0:{b0}:format=yuv420[gg]",
               "[gg][ly]overlay=0:0:format=yuv420[d]",
               f"[d][bn]overlay={bx}:{by}:eof_action=pass:format=yuv420,format=yuv420p,{SP}[v]"]
    fc += [
           f"[2:a]asetrate=48000*{job['pitch']},aresample=48000,atrim=0:{TOTAL},afade=t=in:st=0:d=0.4,"
           f"afade=t=out:st={TOTAL - 0.6}:d=0.6[a]"]
    dest = Path(job["dest"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]",
           "-frames:v", str(NF), "-t", f"{TOTAL}", *G.NVENC, "-c:a", "aac", "-b:a", "192k", *G.CLEAN, str(dest)]
    with gpu_slot():
        for attempt in range(3):
            r = _run_ff(cmd, tmp / f"err{attempt}.txt")
            if r.returncode == 0:
                break
            if attempt == 2 or ("Invalid argument" in r.stderr and attempt == 0):
                (WORK / f"fail_{dest.stem}.txt").write_text(subprocess.list2cmdline(cmd) + 2 * chr(10) + r.stderr,
                                                           encoding="utf-8")
                raise RuntimeError(f"{dest.name}: {r.stderr[-600:]}")
            time.sleep(3)
    shutil.rmtree(tmp, ignore_errors=True)
    return dest.name


# ---------------- исходники ----------------
def prep_segments() -> None:
    """Каждый кусок SPANS → короткая h264-заготовка 30 к/с без B-кадров (читается с нуля на видеокарте), её кадры
    240×135 для расчёта и список кадров-повторов (сбой записи игры: такой кадр посреди движения = микрофриз)."""
    SEGD.mkdir(parents=True, exist_ok=True)

    def one(k):
        kind, name, t0, t1, _pl, _r = SPANS[k]
        src = src_path(kind, name)
        dest = SEGD / f"{k}.mp4"
        G.cut_segment(src, t0, t1, dest, 30)
        _c, sw, sh = G.probe(dest)
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(dest), "-vf", f"scale={CW}:{CH}:flags=area,format=gray",
                              "-f", "rawvideo", "-"], capture_output=True).stdout
        a = np.frombuffer(raw, np.uint8).reshape(-1, CH, CW)
        d = np.abs(np.diff(a.astype(np.int16), axis=0)).mean((1, 2))
        bad = set()
        for i in range(1, len(d)):                         # кадр i+1 = повтор кадра i посреди движения
            if d[i] < 0.12 and (d[i - 1] > 0.5 or (i + 1 < len(d) and d[i + 1] > 0.5)):
                bad.add(i + 1)
        if len(d) and d[0] < 0.12 and len(d) > 1 and d[1] > 0.5:
            bad.add(1)
        return k, dict(path=str(dest), sw=sw, sh=sh, n=len(a), bad=sorted(bad)), a
    with ThreadPoolExecutor(6) as ex:
        for k, meta, a in ex.map(one, list(SPANS)):
            SEG[k] = meta
            SRC[k] = a


# ---------------- план ----------------
def geo(rng: random.Random, rule: str, big: bool) -> dict:
    """Кадр по центру: зум от центра; у геймплея с интерфейсом окно чуть ниже (машина внизу), зум больше.
    big — исходник 2560×1440 (запас по зуму до 1.75 без увеличения)."""
    zmax = 1.75 if big else 1.52                          # 1920-исходники: до 1.52 (увеличение ≤ 1.1×) — квартира упиралась в разброс
    if rule == "air":                                     # облёты/виды города: героя нет — шире зум и сдвиг окна
        return dict(z=round(rng.uniform(1.04, 1.62), 3), ox=round(rng.uniform(0.28, 0.72), 3),
                    oy=round(rng.uniform(0.32, 0.68), 3))
    if rule == "open":                                    # первый кусок: человек в кадре — мягкий зум, окно у центра
        return dict(z=round(rng.uniform(1.0, 1.35 if big else 1.25), 3), ox=round(rng.uniform(0.4, 0.6), 3),
                    oy=round(rng.uniform(0.38, 0.62), 3))
    if rule == "hud":
        return dict(z=round(rng.uniform(1.2, zmax), 3), ox=round(rng.uniform(0.42, 0.58), 3),
                    oy=round(rng.uniform(0.55, 0.78), 3))
    return dict(z=round(rng.uniform(1.04, zmax), 3), ox=round(rng.uniform(0.42, 0.58), 3),
                oy=round(rng.uniform(0.42, 0.58), 3))


def human_in(p: dict, bh: int) -> bool:
    """Ролик начинается с движения: в первые 10 кадров в окне заметное движение (не стоящий кадр)."""
    a = SRC[p["k"]]
    sw, sh = SEG[p["k"]]["sw"], SEG[p["k"]]["sh"]
    x, y, cw, ch = src_rect(p, bh)
    xs = slice(int(x / sw * CW), int((x + cw) / sw * CW) + 1)
    ys = slice(int(y / sh * CH), int((y + ch) / sh * CH) + 1)
    d = np.abs(np.diff(a[p["f0"]:p["f0"] + 11].astype(np.float32), axis=0))
    return d[:, ys, xs].mean() >= OPEN_START


def piece(rng: random.Random, k: str, frames: int, opener_bh: int = 0) -> dict | None:
    sg = SEG[k]
    if frames > sg["n"] - 2:
        return None
    bad = set(sg["bad"])
    for _ in range(40 if opener_bh else 12):
        f0 = rng.randint(0, sg["n"] - frames - 1)
        if not any(f in bad for f in range(f0, f0 + frames + 1)):
            p = dict(k=k, f0=f0, frames=frames)
            p.update(geo(rng, "open" if opener_bh else SPANS[k][5], sg["sw"] > 2000))
            if opener_bh and not human_in(p, opener_bh):
                continue
            return p
    return None


def split(rng: random.Random, parts: int, lo: float, hi: float) -> list[int]:
    """Длины частей в кадрах (сумма = NF), каждая в [lo, hi] секунд."""
    for _ in range(50):
        xs = [rng.uniform(lo, hi) for _ in range(parts)]
        s = sum(xs)
        fr = [round(x * TOTAL / s * FPS) for x in xs]
        fr[-1] = NF - sum(fr[:-1])
        if all(lo * FPS - 2 <= f <= hi * FPS + 2 for f in fr):
            return fr
    return []


def candidate(rng: random.Random, kind: str, bh: int = 750) -> list[dict] | None:
    """15 с = 5–7 частей по 1.6–3.4 с, каждая — один непрерывный план: первая — человек в движении (клиент 17.11),
    одна часть — такси (комментарии про такси), иногда одна — механик, остальные — облёты/виды города (графика);
    соседние части — разные планы и разные ролики."""
    n = rng.choice((5, 6, 6, 7))
    fr = split(rng, n, 1.6, 3.4)
    if not fr:
        return None
    t_pos = rng.randint(1, n - 1)
    rest = [i for i in range(1, n) if i != t_pos]
    m_pos = set(rng.sample(rest, 1)) if MECHS and rng.random() < 0.5 else set()   # механик уже в начале — внутри реже
    keys: list = []
    for i, f in enumerate(fr):
        pool = HUMAN if i == 0 else TAXI if i == t_pos else MECHS if i in m_pos else MAPU
        opts = [k for k in pool if k not in keys and SEG[k]["n"] >= f + 2
                and (not keys or SPANS[k][1] != SPANS[keys[-1]][1] or SPANS[k][0] == "mech")]
        if not opts:
            return None
        keys.append(rng.choice(opts))
    out = []
    for i, (k, f) in enumerate(zip(keys, fr)):
        p = piece(rng, k, f, bh if i == 0 else 0)
        if p is None:
            return None
        out.append(p)
    return out


def make_job(n: int, tag: str, comment: int, rng: random.Random, avatars: list, people: list) -> dict | None:
    pcs = None
    lay = layout(rng, tag, comment, cap_of(tag, n))
    if not lay:
        return None
    for _ in range(40):
        pcs = candidate(rng, KIND[comment], lay["bh"])
        if pcs:
            break
    if not pcs:
        return None
    job = dict(n=n, tag=tag, comment=comment, kind=KIND[comment], pieces=pcs, person=list(rng.choice(people)),
               avatar=str(rng.choice(avatars)), seed=rng.randrange(10 ** 9), shade=rng.randrange(10 ** 9),
               bg=rng.choice((255, 254, 253, 252, 251)), tint=rng.choice((0, 0, 1, -1, 2, -2)),
               pitch=round(rng.uniform(0.975, 1.025), 4), mus=rng.randrange(len(MUSICS)),
               moff=round(rng.uniform(3.5, 30.0), 2), **lay)
    return job


UST = None                                             # core.uniq_fast.FrameStore — кадры заготовок 480×270 (main)


def frames_of(jobs: list[dict], every: bool = False):
    """Кадры роликов для прогноза отпечатков (core.uniq_fast): 6 к/с (как проверка: кадр 5i+2) или каждый кадр."""
    fr = np.arange(NF) if every else np.array([min(NF - 1, round(i * FPS / HFPS) + 2) for i in range(round(TOTAL * HFPS))])
    idx, box, scale, A, C = [], [], [], [], []
    for job in jobs:
        starts = np.cumsum([0] + [p["frames"] for p in job["pieces"]])
        j = np.searchsorted(starts, fr, side="right") - 1
        pb = [UF.strip_box(tuple(G._even(t) for t in src_rect(p, job["bh"])), job["b0"], job["bh"], STRIP)
              for p in job["pieces"]]
        idx.append(np.array([UST.off[job["pieces"][q]["k"]] + job["pieces"][q]["f0"] for q in j]) + fr - starts[j])
        box.append(np.array([pb[q] for q in j], np.float32))
        scale.append(np.array([UF.CW / SEG[job["pieces"][q]["k"]]["sw"] for q in j], np.float32))
        sh = shade_field(job["shade"], W // 4, H // 4)[STRIP[0] // 4:STRIP[1] // 4]
        a, c = UF.shade_cells(sh, SHADE_AMP)
        A.append(np.repeat(a[None], len(fr), 0))
        C.append(np.repeat(c[None], len(fr), 0))
    return UF.Frames(np.concatenate(idx), np.concatenate(box), np.concatenate(scale), np.concatenate(A),
                     np.concatenate(C), len(fr))


def predict(job: dict):
    """Прогноз отпечатков одного ролика (6 к/с) — (H, M) half на видеокарте [кадров, 256]."""
    H_, M_ = UF.predict(UST, frames_of([job]))
    return H_[0], M_[0]


Bank = UF.Bank


def plan_jobs(slots: list[tuple[str, int, int]], bank, rng: random.Random, avatars, people, tries: int,
              label: str, out_dir) -> list[dict]:
    """Ролик за роликом: варианты пачками по 24 (прогноз и расстояние — одним расчётом на видеокарте), берётся самый
    далёкий от уже взятых и прошлых партий; хватило запаса PLAN_THR — дальше не перебираем."""
    import torch
    jobs, worst, t0 = [], [], time.time()
    for k, (tag, n, comment) in enumerate(slots, 1):
        best = None
        for _ in range(0, tries, 24):
            cands = [c for c in (make_job(n, tag, comment, rng, avatars, people) for _ in range(24)) if c]
            if not cands:
                continue
            Hh, Mm = UF.predict(UST, frames_of(cands))
            d = bank.min_dist(Hh)
            i = int(torch.argmax(d))
            if best is None or float(d[i]) > best[0]:
                best = (float(d[i]), cands[i], Hh[i], Mm[i])
            if best[0] > PLAN_THR:
                break
        d, j, Hh, Mm = best
        j["plan_dist"] = round(d, 1)
        bank.add(Hh, Mm)
        j["dest"] = str(out_dir(tag) / vname(j))
        jobs.append(j)
        worst.append(d)
        if len(slots) > 1:
            prog(f"{label}: варианты роликов по отпечаткам", k, len(slots))
        if k % 50 == 0:
            print(f"  {label}: {k}/{len(slots)}, у последнего ближайший чужой кадр {d:.0f} бит, {time.time() - t0:.0f} с",
                  flush=True)
    w = sorted(worst)
    print(f"{label}: {len(jobs)} роликов за {time.time() - t0:.0f} с; ближайший чужой кадр — минимум {w[0]:.0f} бит, "
          f"медиана {w[len(w) // 2]:.0f}; ≤ {THR} бит: {sum(x <= THR for x in w)}, ≤ {PLAN_THR}: {sum(x <= PLAN_THR for x in w)}",
          flush=True)
    return jobs


# ---------------- приёмка по настоящим файлам ----------------
def real_hash(path: Path) -> np.ndarray:
    """КАЖДЫЙ кадр готового ролика (30 к/с): (кадры, 2, 256) — обычный и зеркальный отпечаток."""
    h, m = UF.real_hash(path, STRIP)
    return np.stack([h, m], 1)


def frame_check(job: dict, path: Path, margin: float = 0.8, junk: float = 14.0) -> list:
    """КАЖДЫЙ кадр ролика против того кадра исходника, который должен стоять (юзер 13.11: «фризит, лагает, зелёное»):
    полоса геймплея (выше промокода/логотипа) сравнивается с кадрами исходника k−3…k+3 (та же обрезка и волны света).
    Плохо: ближе другой кадр исходника (повтор = фриз, пропуск = рывок) или ни один не похож (мусор/зелёный)."""
    b0, bh = job["b0"], job["bh"]
    rows = (bh - 200) - (bh - 200) % Q
    w8, h8, rh = W // Q, rows // Q, max(1, round(bh / Q))
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf",
                          f"crop={W}:{rows}:0:{b0},scale={w8}:{h8}:flags=area,format=gray", "-f", "rawvideo", "-"],
                         capture_output=True).stdout
    out = np.frombuffer(raw, np.uint8).reshape(-1, h8, w8).astype(np.float32)
    v = shade_field(job["shade"], W // Q, H // Q)[round(b0 / Q):round(b0 / Q) + h8]
    sa, sc = np.abs(v) * SHADE_AMP, np.where(v < 0, 255.0, 0.0)
    starts = np.cumsum([0] + [p["frames"] for p in job["pieces"]])
    cache: dict = {}

    def expect(p: dict, k: int) -> np.ndarray:
        key = (p["k"], k, p["z"], p["ox"], p["oy"])
        if key not in cache:
            sg = SEG[p["k"]]
            sx, sy = CW / sg["sw"], CH / sg["sh"]
            x, y, cw, ch = src_rect(p, bh)
            im = Image.fromarray(SRC[p["k"]][k]).resize((w8, rh), Image.Resampling.BILINEAR,
                                                        box=(x * sx, y * sy, (x + cw) * sx, (y + ch) * sy))
            cache[key] = np.asarray(im, np.float32)[:h8] * (1 - sa) + sc * sa
        return cache[key]
    flags = []
    if len(out) != NF:
        return [("кадров", len(out))]
    for f in range(NF):
        j = int(np.searchsorted(starts, f, side="right")) - 1
        p = job["pieces"][j]
        k = p["f0"] + f - starts[j]
        n = len(SRC[p["k"]])
        d = {dk: float(np.abs(out[f] - expect(p, k + dk)).mean()) for dk in range(-3, 4) if 0 <= k + dk < n}
        best = min(d, key=d.get)
        if d[best] > junk:
            flags.append((f, "мусор", round(d[best], 1)))
        elif best != 0 and d[0] - d[best] > margin:
            flags.append((f, best, round(d[0] - d[best], 2)))
    return flags


def check_one(job: dict) -> tuple:
    path = Path(job["dest"])
    return real_hash(path), G.bad_frames(path), frame_check(job, path)


def render_accept(jobs: list[dict], bank: Bank, pools: dict, ctx: dict, max_fail: int = 8) -> None:
    """Все ролики сразу в очередь видеокарты; каждый готовый сразу проверяется (потоки) и попадает в папку, только
    если: ни один его кадр (6 и 3 к/с) не ближе THR к принятым и прошлым партиям; нет пустых/зелёных кадров и
    повторов посреди движения (bad_frames); КАЖДЫЙ кадр — ровно тот кадр исходника, что в плане (frame_check).
    Иначе — новый вариант этого слота (план с учётом принятых и ещё собирающихся)."""
    from concurrent.futures import FIRST_COMPLETED, wait
    import queue
    import threading
    import torch
    fails: dict = {}
    done, rej, t0 = 0, 0, time.time()
    cand_dir = WORK / f"cand_{os.getpid()}"
    segs = {k: SEG[k] for k in SPANS}
    pending: dict = {}                                    # слот → предсказанные хэши ещё не принятого ролика
    chk = ThreadPoolExecutor(8)
    building, checking = {}, {}
    # 17.11: замена (новый план) считалась прямо в цикле — 15–25 с, и всё это время готовые ролики не проверялись и не
    # принимались (70 собранных кандидатов лежали без дела). Теперь замены считает отдельный поток, цикл не ждёт.
    lock = threading.RLock()                              # банк и pending — общие для цикла и потока замен
    rq: queue.Queue = queue.Queue()                       # забракованные слоты → поток замен
    ready: queue.Queue = queue.Queue()                    # новые варианты → в очередь видеокарты
    outstanding = 0

    def submit(j: dict) -> None:
        key = (j["tag"], j["n"])
        j["final"] = j.get("final") or j["dest"]
        j["dest"] = str(cand_dir / f"{j['tag']}_{j['n']:03d}_{fails.get(key, 0)}.mp4")
        j["segs"] = segs
        pr = predict(j)
        with lock:
            pending[key] = pr
        building[pools[j["tag"]].submit(build, j)] = j

    def replanner() -> None:
        while True:
            j = rq.get()
            if j is None:
                return
            try:
                with lock:
                    b2 = bank.copy()
                    for Hh, Mm in pending.values():
                        b2.add(Hh, Mm)
                nj = plan_jobs([(j["tag"], j["n"], j["comment"])], b2, ctx["rng"], ctx["avatars"], ctx["people"],
                               ctx["tries"], f"  новый вариант {vname(j)}", ctx["out_dir"])[0]
                nj["final"] = nj["dest"] = j["final"]
                if ctx.get("plan_save"):                  # в план: после перезапуска не собирать снова забракованный
                    ctx["plan_save"]((j["tag"], j["n"]), {k: v for k, v in nj.items() if k not in ("segs", "final")})
                del b2
                ready.put(nj)
            except Exception as e:                          # noqa: BLE001
                print(f"  ОШИБКА замены {vname(j)}: {str(e)[:200]}", flush=True)
                ready.put(("retry", j))
    th = threading.Thread(target=replanner, daemon=True)
    th.start()
    for j in jobs:
        submit(j)
    while building or checking or outstanding:
        while not ready.empty():
            nj = ready.get()
            outstanding -= 1
            if isinstance(nj, tuple):                      # замена не посчиталась — ещё раз
                rq.put(nj[1])
                outstanding += 1
                continue
            submit(nj)
        if not (building or checking):
            time.sleep(0.3)
            continue
        fin, _ = wait(list(building) + list(checking), timeout=1.0, return_when=FIRST_COMPLETED)
        for fu in fin:
            if fu in building:
                j = building.pop(fu)
                fu.result()
                checking[chk.submit(check_one, j)] = j
                continue
            j = checking.pop(fu)
            try:
                h, bad, fr = fu.result()
            except Exception as e:                          # noqa: BLE001 — сбой проверки одного ролика не роняет партию
                print(f"  ОШИБКА проверки {Path(j['dest']).name}: {str(e)[:200]} — пересобираю", flush=True)
                h, bad, fr = np.zeros((1, 2, 256), np.float16), [], [("проверка упала",)]
            j.pop("segs", None)
            key = (j["tag"], j["n"])
            with lock:
                d = float(bank.min_dist(torch.tensor(h[:, 0])[None])[0])
                ok = d > THR and not bad and not fr
                if ok:
                    bank.add(h[:, 0], h[:, 1])
                pending.pop(key, None)
            if ok:
                Path(j["final"]).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(j["dest"], j["final"])
                j["dest"] = j.pop("final")
                j["min_dist"] = d
                ctx["hash30"][str(Path(j["dest"]))] = h
                if ctx.get("save_hash") and done % 10 == 9:  # кэш отпечатков — по ходу (после падения не считать заново)
                    ctx["save_hash"]()
                ctx["accepted"].append(j)
                done += 1
                ctx["tick"](done, rej)
                if done % 25 == 0:
                    print(f"  принято {done}, заменено {rej}, {time.time() - t0:.0f} с", flush=True)
                continue
            rej += 1
            why = f"bad_frames {bad[:6]}" if bad else f"кадры не те {fr[:6]}" if fr else f"ближайший чужой кадр {d:.0f} бит"
            print(f"  замена {vname(j)}: {why}", flush=True)
            ctx["tick"](done, rej)
            fails[key] = fails.get(key, 0) + 1
            Path(j["dest"]).unlink(missing_ok=True)
            if fails[key] > max_fail:
                raise SystemExit(f"{vname(j)}: {max_fail} вариантов подряд не прошли — нужен шире разброс")
            rq.put(j)
            outstanding += 1
    rq.put(None)
    chk.shutdown()
    print(f"  принято {done}, заменено {rej}, {time.time() - t0:.0f} с", flush=True)


def prep_assets(B) -> None:
    """Один раз до воркеров: анимация баннера KO (6-секундная петля клиента → на всё время с 1-й с, влёт как в 1309),
    музыка (звук роликов Map Update, −18 LUFS), эмодзи, кэш отпечатков прошлых партий из OneState 5."""
    import assemble_ugc_reels as A
    WORK.mkdir(parents=True, exist_ok=True)
    for f in ("refs6.npz", "refs3.npz"):
        src = ROOT / "output" / "_work" / "onestate5" / f
        if src.exists() and not (WORK / f).exists():
            shutil.copy2(src, WORK / f)
    for (key, name), out in zip(MU_FILES.items(), MUSICS):
        if not out.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(MU / f"{name}.mp4"), "-vn", "-af",
                            "loudnorm=I=-18:TP=-2:LRA=11", "-ar", "48000", "-ac", "2", str(out)], check=True)
    for t in [ln for c in CAPTIONS_KO + COMMENTS_KO for ln in c]:
        for kind, chunk in A._tokenize_runs(t):
            if kind == "emoji":
                A._apple_emoji_rgba(chunk, 60)
    bw = B.B_W
    bh = round((B.B_CROP[3] - B.B_CROP[1]) * bw / (B.B_CROP[2] - B.B_CROP[0]))
    cw, ch = round(bw * 1.12 / 2) * 2, round(bh * 1.12 / 2) * 2
    if B.BANNER_ANIM.exists():
        return
    fw, fh = B.B_CROP[2] - B.B_CROP[0], B.B_CROP[3] - B.B_CROP[1]
    dur = TOTAL - BANNER_T + 0.3
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-stream_loop", "-1", "-i", str(KO_BANNER), "-t", f"{dur:.2f}", "-vf",
                            f"fps={FPS},crop={fw}:{fh}:{B.B_CROP[0]}:{B.B_CROP[1]}", "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
                           stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{cw}x{ch}", "-r",
                            str(FPS), "-i", "-", "-c:v", "png", str(B.BANNER_ANIM)], stdin=subprocess.PIPE)
    fs = fw * fh * 4
    for k in range(round(dur * FPS)):
        t = k / FPS
        buf = dec.stdout.read(fs)
        if len(buf) < fs:
            break
        fr = Image.frombuffer("RGBA", (fw, fh), buf)
        u = min(1.0, t / B.B_POP)
        sc = 0.55 + 1.0 * u if u < 0.5 else 1.05 - 0.1 * (u - 0.5)       # 0.55 → 1.05 → 1.0
        a = min(1.0, t / 0.12)
        w, h = max(2, round(bw * sc)), max(2, round(bh * sc))
        im = fr.resize((w, h), Image.Resampling.LANCZOS)
        if a < 1:
            im.putalpha(im.getchannel("A").point(lambda v, a=a: int(v * a)))
        can = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        can.alpha_composite(im, ((cw - w) // 2, (ch - h) // 2))
        enc.stdin.write(can.tobytes())
    enc.stdin.close()
    enc.wait()
    dec.kill()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--prep", action="store_true", help="только подготовка: заготовки, хэши прошлых партий, план")
    ap.add_argument("--dec", default=DEC, choices=("cuvid", "cuvid32", "cuvid8", "nvdec"))
    ap.add_argument("--tt", type=int, default=0)
    ap.add_argument("--yt", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--seed", type=int, default=51116)
    ap.add_argument("--tries", type=int, default=600)
    ap.add_argument("--thr", type=int, default=48, help="приёмка: ни один кадр не ближе стольких бит из 256 (запас к 40)")
    a = ap.parse_args()
    global THR, PLAN_THR, UST
    THR, PLAN_THR = a.thr, a.thr + 10                   # план с запасом: ошибка прогноза ~7 бит (95 % ≤ 12)
    if os.environ.get("UF_DEV") == "cpu":              # 17.11: расчёт на процессоре брал 6+ ядер → рендерам не хватало,
        import torch                                     # кадры сбивались, брака больше — замкнутый круг
        torch.set_num_threads(int(os.environ.get("TORCH_THREADS", "4")))
    WORK.mkdir(parents=True, exist_ok=True)
    _init_font("default")
    B = _M["B"]
    prep_assets(B)
    t0 = time.time()
    prep_segments()
    UST = UF.FrameStore()
    UST.load({k: Path(v["path"]) for k, v in SEG.items()})
    print(f"исходники: {len(SEG)} кусков, повторов кадров: "
          f"{ {k: len(v['bad']) for k, v in SEG.items() if v['bad']} }, {time.time() - t0:.0f} с", flush=True)
    os.environ["OS5_DEC"] = a.dec                       # воркеры наследуют способ распаковки
    pools = {tag: ProcessPoolExecutor(a.jobs, initializer=_init_font, initargs=(FONT[tag],)) for tag in ("tt", "yt")}
    for tag in ("tt", "yt"):
        TABLE[FONT[tag]] = pools[tag].submit(_table).result()
    print("строк в карточках:", {f: TABLE[f]["lines"] for f in TABLE}, flush=True)
    avatars = [p for d in B.AVATAR_DIRS if d.is_dir() for p in sorted(d.glob("*.jpg")) if not p.name.startswith("_")]
    people = [tuple(p) for p in B.PEOPLE]

    ref_dirs = REFS[:4] if a.test else REFS              # тест: только партии с готовыми хэшами (OneState 4, 1310_v2)
    # папки могут быть переименованы юзером с ID впереди (17.11: 1576_onestate_mic_TT_200) — ищем и «*_имя»
    ref_paths = [p for d in ref_dirs for p in [ROOT / "output" / d] + sorted((ROOT / "output").glob(f"*_{d}")) if p.is_dir()]
    refs = [f for p in ref_paths for f in sorted(p.glob("*.mp4"))]
    bank = Bank()
    for fps in (6, 3):
        R = hashes(refs, [STRIP], fps, WORK / f"refs{fps}.npz")
        for f in refs:
            bank.add(R[str(f)][:, 0], R[str(f)][:, 1])
    print(f"прошлые партии в сравнении: {len(refs)} роликов, {time.time() - t0:.0f} с", flush=True)
    import torch
    torch.cuda.empty_cache()                             # кэш расчёта отдать: иначе очередь видеокарты (лимит) не пустит сборки

    rng = random.Random(a.seed)
    if a.test:
        out_dir = lambda tag: WORK / "test"           # noqa: E731
        slots = [("tt" if c % 2 == 0 else "yt", c + 1, c) for c in range(len(COMMENTS_RAW))]
    else:
        out = {"tt": ROOT / "output" / f"{NAME}_TT_{a.tt}", "yt": ROOT / "output" / f"{NAME}_YT_{a.yt}"}
        out_dir = lambda tag: out[tag]                 # noqa: E731
        slots = [(tag, n, (n - 1) % len(COMMENTS_RAW))
                 for tag, cnt in (("tt", a.tt), ("yt", a.yt)) for n in range(1, cnt + 1)]
    pf = WORK / f"plan_{a.seed}_{'test' if a.test else f'{a.tt}_{a.yt}'}.json"
    if pf.exists():
        jobs = json.loads(pf.read_text(encoding="utf-8"))
    else:
        jobs = plan_jobs(slots, bank.copy(), rng, avatars, people, a.tries, "план", out_dir)
        pf.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
    if a.prep:
        print(f"ПЛАН ГОТОВ: {len(jobs)} роликов → {pf}", flush=True)
        for p_ in pools.values():
            p_.shutdown()
        return 0
    torch.cuda.empty_cache()
    todo = [j for j in jobs if not Path(j["dest"]).exists()]
    have = [Path(j["dest"]) for j in jobs if Path(j["dest"]).exists()]
    hcf = WORK / f"hash30_{a.seed}_{a.tt}_{a.yt}.npz"    # отпечатки каждого кадра готовых роликов (кэш: путь → (h, mtime))
    hc = dict(np.load(hcf, allow_pickle=True)["d"].item()) if hcf.exists() else {}
    hash30 = {}

    def get30(f: Path):
        c = hc.get(str(f))
        return c[0] if c is not None and c[1] == f.stat().st_mtime else real_hash(f)
    with ThreadPoolExecutor(8) as ex:                    # готовые ролики (перезапуск) — из кэша или в потоках
        for i, (f, h) in enumerate(zip(have, ex.map(get30, have)), 1):
            hash30[str(f)] = h
            bank.add(h[:, 0], h[:, 1])
            if i % 5 == 0 or i == len(have):
                prog("отпечатки готовых роликов (каждый кадр)", i, len(have))
    if have:
        print(f"готовых роликов в сравнении: {len(have)}, {time.time() - t0:.0f} с", flush=True)
    progf = WORK / "progress.json"
    total = len(jobs)

    def tick(done: int, rej: int = 0) -> None:
        progf.write_text(json.dumps(dict(done=total - len(todo) + done, total=total)), encoding="utf-8")
        prog(f"сборка + проверка каждого ролика (заменено {rej})", total - len(todo) + done, total)
    tick(0)
    def plan_save(key: tuple, nj: dict) -> None:
        for i, jj in enumerate(jobs):
            if (jj["tag"], jj["n"]) == key:
                jobs[i] = nj
        # в файл — чистые копии: submit() меняет dest на временный файл-кандидат (17.11 после перезапуска это приняло
        # недособранный кандидат за готовый ролик) — пишем итоговый путь и без служебных полей
        clean = []
        for jj in jobs:
            c = {k: v for k, v in jj.items() if k not in ("segs", "final")}
            c["dest"] = jj.get("final") or jj["dest"]
            clean.append(c)
        tmp = pf.with_suffix(".tmp")
        tmp.write_text(json.dumps(clean, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, pf)
    ctx = dict(accepted=[], rng=random.Random(a.seed + 7 + len(have)), avatars=avatars, people=people, tries=a.tries,
               out_dir=out_dir, tick=tick, hash30=hash30, plan_save=None if a.test else plan_save,
               save_hash=lambda: np.savez(hcf, d=np.array({k: (v, Path(k).stat().st_mtime) for k, v in dict(hash30).items()
                                                         if Path(k).exists()}, dtype=object)))
    render_accept(todo, bank, pools, ctx)
    (WORK / f"accepted_{pf.stem}.json").write_text(json.dumps(ctx["accepted"], ensure_ascii=False), encoding="utf-8")
    np.savez(hcf, d=np.array({k: (v, Path(k).stat().st_mtime) for k, v in hash30.items() if Path(k).exists()}, dtype=object))
    err = []
    for j in ctx["accepted"]:
        p = predict(j)[0].float().cpu().numpy()
        r = vhash(Path(j["dest"]), [STRIP], 6)[:, 0].astype(np.float32)
        m = min(len(p), len(r))
        err.append(np.abs(p[:m] - r[:m]).sum(1))
    if err:
        e = np.concatenate(err)
        print(f"ошибка расчёта до рендера, бит на кадр: среднее {e.mean():.1f}, 95 % {np.percentile(e, 95):.0f}", flush=True)
    prog("итоговая проверка: каждый кадр всех пар (отдельный процесс check_uniq_allframes)", 0, None)
    subprocess.run([sys.executable, str(ROOT / "check_uniq_allframes.py"), *{str(Path(j["dest"]).parent) for j in jobs},
                    "--strip", str(STRIP[0]), str(STRIP[1]), "--refs-cache", str(WORK / "refs6.npz"), "--hash-cache", str(hcf)])
    for p in pools.values():
        p.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
