#!/usr/bin/env python3
"""
Видео-вставки с Pinterest под кадр референса: поиск видео по запросам +
«похожие пины» лучших находок → фильтры (вертикальное, длина, метка ИИ,
стоп-слова, повторы, монтаж из разных планов, текст поверх кадра) → оценка
SigLIP (кадры против кадра референса и описания сцены, минус «анти»-описания)
→ лист кандидатов для ручного отбора → скачивание выбранных 720p mp4.

Важно не только «что в кадре», но и КТО снимает и как: вставки должны
выглядеть как живое видео с телефона (девушка снимает парня / парень сам
себя), не промо и не кино.

  python harvest_pin_videos.py --profile car --out downloads/1254/broll/car
  python harvest_pin_videos.py --profile car --out downloads/1254/broll/car --pick 3,7,12
  python harvest_pin_videos.py --profile laptop --like downloads/1254/broll/laptop/_v2 --out downloads/1254/broll/laptop/_more

--like DIR — «ещё похожих на эти»: кадры отобранных видео из DIR — эталон, их
«похожие пины» — затравка поиска; всё, что уже есть в DIR или было на его листе, пропускается.

Без --pick: <out>/_candidates.jpg + _candidates.json (номера на листе).
С --pick N,N,…: скачать эти номера в <out>/NN_<pin>.mp4.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core.harvester import API_HEADERS_BASE, HTML_HEADERS, _ai_flag_from_obj, _text_looks_like_ai  # noqa: E402

FF = r"C:\Users\user\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"
REF_VIDEO = ROOT / "downloads" / "1254" / "ref" / "ref_DdXKFuNzk1c.mp4"
REF_TEXT_BAND = (0.33, 0.86)  # где в рефе текст — на эталоне размываем

# 1254 — реф UNO-рилса: девушка снимает парня. ref_t — секунды кадра в рефе.
PROFILES: dict[str, dict] = {
    "car": {
        "ref_t": [0.3, 0.8], "refs": [],
        "texts": ["filmed from the passenger seat at night: the boyfriend driving, steering wheel and glowing "
                  "car screen, dark calm car interior, amateur phone video",
                  "inside a dark car at night seen from the passenger side, man's hand on the steering wheel, "
                  "lit infotainment display"],
        "neg": ["first-person view from the driver's seat, speedometer, fast driving on a highway",
                "sports car racing at high speed, drifting",
                "professional cinematic car commercial",
                "a woman's hands with long nails on the steering wheel"],
        "ban": r"\b(speed|km/?h|mph|race|racing|drift|0-100|launch|exhaust|turbo|hp|horsepower)\b",
        "ocr_max": 25,  # приборка / навигатор — мелкий текст допустим
        "queries": ["boyfriend driving at night", "filming my boyfriend driving", "him driving at night",
                    "passenger seat pov night", "watching him drive", "late night drive with him",
                    "boyfriend driving aesthetic", "my man driving at night", "night drive passenger seat",
                    "passenger princess", "passenger princess night", "passenger princess pov",
                    "bf driving at night", "night ride with bf", "driving with my boyfriend at night"],
    },
    "gym": {
        "ref_t": [1.3, 1.8], "refs": [ROOT / "downloads" / "1254" / "gym" / "04_613545149279514588.jpg"],
        "texts": ["amateur phone video of a young guy in a hoodie training on a gym machine, casual "
                  "self-filmed gym clip, dark gym",
                  "guy working out in a gym, filmed on a phone propped on the floor, everyday gym vlog"],
        "neg": ["professional cinematic fitness commercial with dramatic lighting and logo",
                "shirtless bodybuilder flexing and posing",
                "woman working out in the gym",
                "motivational quote text on screen"],
        "ban": r"\b(promo|sale|brand|collection|apparel|discount|shop|merch|coaching|ebook)\b",
        "ocr_max": 6,
        "queries": ["gym pov", "gym vlog men", "boyfriend at the gym", "gym day pov hoodie",
                    "my gym session pov", "gym fit check men", "5am gym pov", "late night gym pov",
                    "pull day pov", "gym diary men"],
    },
    # зал от первого лица, лица нет вообще (в кадре 4 виден наш парень — чужое лицо в зале выдаст подмену).
    # Эталон — POV-беговая дорожка, отобранная раньше: --like downloads/1254/broll/gym_pov/_seed
    "gym_pov": {
        "ref_t": [], "refs": [],
        "texts": ["first-person POV video in a gym: the camera is the guy's own eyes, we only see his hands, arms "
                  "and legs on a treadmill, dumbbells or machine handles, no face",
                  "point-of-view gym clip filmed on a phone, looking down at his own hands gripping a barbell, "
                  "casual amateur footage"],
        "neg": ["selfie video of a man's face in the gym",
                "mirror selfie in the gym",
                "a woman's hands with long painted nails",
                "a woman's legs in leggings or shorts, female glutes workout",
                "professional cinematic fitness commercial",
                "motivational quote text on screen"],
        "ban": r"\b(promo|sale|brand|collection|apparel|discount|shop|merch|coaching|ebook|glute|booty|girl|women)\b",
        "ocr_max": 15,  # табло дорожки / цифры на тренажёре допустимы
        "no_face": True,
        "queries": ["gym pov", "pov treadmill", "treadmill pov running", "incline walk pov", "stairmaster pov",
                    "pov lifting weights", "pov bench press", "pov deadlift", "pov dumbbell curls",
                    "pov leg press", "pov lat pulldown", "pov cable machine", "first person gym workout",
                    "gym pov men"],
    },
    # 1256 — тот же формат, но парень рассказывает о своей девушке. Всё от ПЕРВОГО ЛИЦА (её глазами), лиц нет:
    # её руки на руле / её ноги на беговой дорожке / её руки на клавиатуре. Эталон — --like <кат>/_seed
    "car_gf": {
        "ref_t": [], "refs": [],
        "texts": ["first-person POV from the driver's seat at night: a young woman's hands with manicure and rings "
                  "on the steering wheel, glowing dashboard, calm drive, amateur phone video",
                  "girl driving at night, view over her own hands on the wheel, nails, bracelets, city lights"],
        "neg": ["a man's hairy hand on the steering wheel",
                "view from the passenger seat at the driver",
                "speedometer, racing fast on a highway, drifting",
                "professional cinematic car commercial"],
        "ban": r"\b(speed|km/?h|mph|race|racing|drift|0-100|launch|exhaust|turbo|hp|horsepower)\b",
        "ocr_max": 25,
        "no_face": True,
        "queries": ["pov driving at night girl", "pov girl driving", "night drive pov nails", "girl hands steering wheel pov",
                    "pov driving aesthetic nails", "late night drive pov girl", "driving pov rings",
                    "girly car aesthetic driving", "pov driving my car at night", "night drive aesthetic pov"],
    },
    "gym_gf": {
        "ref_t": [], "refs": [],
        "texts": ["first-person POV on a treadmill looking down: a young woman's legs in leggings and sneakers walking, "
                  "treadmill belt and console, no face, amateur phone video",
                  "girl's POV in the gym on a treadmill or stairmaster, her sneakers and legs from above"],
        "neg": ["a man's hairy legs",
                "close-up of glutes, revealing outfit, provocative pose",
                "professional cinematic fitness commercial",
                "motivational quote text on screen"],
        "ban": r"\b(promo|sale|brand|collection|apparel|discount|shop|merch|coaching|ebook|booty|bikini)\b",
        "ocr_max": 15,
        "no_face": True,
        "queries": ["treadmill pov girl", "incline walk pov", "pov treadmill aesthetic", "girl treadmill pov",
                    "12 3 30 treadmill pov", "hot girl walk treadmill", "stairmaster pov girl", "pov gym girl treadmill",
                    "treadmill aesthetic", "pov walking on treadmill"],
    },
    "laptop_gf": {
        "ref_t": [], "refs": [],
        "texts": ["first-person POV: a young woman's hands with manicure and rings typing on a laptop at night, cozy "
                  "sweater sleeves, glowing screen, dark room, amateur phone video",
                  "girl typing on a laptop keyboard, close-up of her hands, late night work"],
        "neg": ["professional product advertisement of a laptop",
                "a man's hands typing on a keyboard",
                "motivational quote text on screen"],
        "ban": r"\b(promo|sale|discount|shop|course)\b",
        "ocr_max": None,
        "no_face": True,
        "queries": ["pov typing laptop night", "girl hands typing laptop aesthetic", "late night study pov laptop",
                    "pov working late laptop aesthetic", "nails typing laptop", "study with me pov night",
                    "pov coding girl", "cozy laptop pov night", "aesthetic typing laptop", "typing asmr laptop"],
    },
    "laptop": {
        "ref_t": [2.2, 2.7], "refs": [],
        "texts": ["laptop screen with code at night, external monitor behind, keyboard, dark room, "
                  "amateur phone video",
                  "guy working late on a laptop at night, filmed casually on a phone over his shoulder"],
        "neg": ["professional product advertisement of a laptop",
                "motivational quote text on screen",
                "cozy study desk with books, candles and notebooks"],
        "ban": r"\b(promo|sale|discount|shop|course)\b",
        "ocr_max": None,  # на экране код — OCR не применим
        "queries": ["coding at night", "boyfriend coding at night", "late night coding pov",
                    "my boyfriend working late", "software engineer night pov", "working late at night laptop",
                    "programmer night setup pov", "late night grind laptop", "coding vlog night",
                    "startup founder late night work"],
    },
}
PAGES = 2            # страниц поиска на запрос (по 25)
DUR_MIN, DUR_MAX = 3.0, 90.0
TOP_FRAMES = 80      # сколько лучших по превью проверять по кадрам
N_FRAMES = 4
CONT_MIN = 0.78      # мин. схожесть соседних кадров: ниже — монтаж из разных планов (промо-эдит)
SHEET_N = 36


class Pin:
    def __init__(self, obj: dict) -> None:
        v = (obj.get("videos") or {}).get("video_list") or {}
        best = max(v.values(), key=lambda x: x.get("width", 0))
        self.id = str(obj["id"])
        self.hls = best["url"]
        self.w, self.h = best.get("width", 0), best.get("height", 0)
        self.dur = (best.get("duration") or 0) / 1000
        self.thumb = best.get("thumbnail") or ""
        self.title = (obj.get("grid_title") or obj.get("title") or "")[:60]
        self.text = " ".join(str(obj.get(k) or "") for k in ("title", "grid_title", "description",
                                                              "closeup_unified_description"))
        self.found_by = ""
        self.parts = (0.0, 0.0, 0.0)  # (похожесть на реф, на описание, на анти-описание)
        self.score = 0.0
        self.cont = 1.0

    @property
    def mp4(self) -> str:
        # hls/<a>/<b>/<c>/<sig>.m3u8 → mc/720p/<a>/<b>/<c>/<sig>.mp4
        tail = self.hls.split("/hls/")[-1].replace(".m3u8", ".mp4")
        return f"https://v1.pinimg.com/videos/mc/720p/{tail}"


class Client:
    def __init__(self) -> None:
        self.cli = httpx.Client(follow_redirects=True, timeout=40, headers=HTML_HEADERS)
        self.cli.get("https://www.pinterest.com/")
        self.csrf = self.cli.cookies.get("csrftoken") or ""

    def _post(self, resource: str, source: str, options: dict) -> dict:
        h = dict(API_HEADERS_BASE, Referer="https://www.pinterest.com" + source)
        if self.csrf:
            h["X-CSRFToken"] = self.csrf
        r = self.cli.post(f"https://www.pinterest.com/resource/{resource}/get/", headers=h,
                          data={"source_url": source, "data": json.dumps({"options": options, "context": {}})})
        return r.json() if r.status_code == 200 and r.content[:1] == b"{" else {}

    def search(self, q: str, pages: int) -> list[dict]:
        out, bm = [], []
        for _ in range(pages):
            js = self._post("BaseSearchResource", f"/search/videos/?q={q}",
                            {"query": q, "scope": "videos", "page_size": 25, "bookmarks": bm})
            data = (js.get("resource_response") or {}).get("data") or {}
            out += data.get("results", []) if isinstance(data, dict) else []
            bm = [js.get("resource_response", {}).get("bookmark")] if js else []
            if not bm or not bm[0]:
                break
        return out

    def related(self, pin_id: str) -> list[dict]:
        js = self._post("RelatedModulesResource", f"/pin/{pin_id}/",
                        {"pin_id": pin_id, "context_pin_ids": [], "page_size": 50, "search_query": "",
                         "source": "deep_linking", "top_level_source": "deep_linking",
                         "top_level_source_depth": 1, "is_pdp": False, "bookmarks": [""]})
        data = (js.get("resource_response") or {}).get("data") or []
        return data if isinstance(data, list) else []


def usable(obj: dict, ban: str) -> Pin | None:
    if not (obj.get("videos") or {}).get("video_list"):
        return None
    if _ai_flag_from_obj(obj) is True or _text_looks_like_ai(obj):
        return None
    p = Pin(obj)
    if p.h < p.w * 1.5 or not (DUR_MIN <= p.dur <= DUR_MAX) or "/hls/" not in p.hls:
        return None
    if ban and re.search(ban, p.text, re.I):
        return None
    return p


def ref_frame(t: float, work: Path) -> Image.Image:
    """Кадр референса с размытой полосой текста — эталон без букв."""
    dest = work / f"_ref_{t:.2f}.png"
    if not dest.exists():
        subprocess.run([FF, "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(REF_VIDEO), "-frames:v", "1",
                        "-vf", "scale=540:960", str(dest)], stdin=subprocess.DEVNULL, check=True)
    im = Image.open(dest).convert("RGB")
    y0, y1 = (int(f * im.height) for f in REF_TEXT_BAND)
    band = im.crop((0, y0, im.width, y1)).filter(ImageFilter.GaussianBlur(28))
    im.paste(band, (0, y0))
    return im


def frames(p: Pin, work: Path, n: int = N_FRAMES) -> list[Image.Image]:
    """n кадров по длине видео (seek прямо по http)."""
    out = []
    for k in range(n):
        t = p.dur * (0.12 + 0.76 * k / max(1, n - 1))
        dest = work / f"{p.id}_{n}_{k}.jpg"
        for src in (p.mp4, p.hls):  # не у всех есть 720p mp4 → HLS
            if dest.exists():
                break
            subprocess.run([FF, "-v", "quiet", "-y", "-ss", f"{t:.2f}", "-headers",
                            "Referer: https://www.pinterest.com/\r\n", "-i", src, "-frames:v", "1",
                            "-vf", "scale=360:-2", str(dest)], stdin=subprocess.DEVNULL, timeout=60)
        if dest.exists():
            out.append(Image.open(dest).convert("RGB"))
    return out


def local_frames(path: Path, n: int = 3) -> list[Image.Image]:
    """n кадров из локального видео (для --like)."""
    dur = float(subprocess.run([FF.replace("ffmpeg.exe", "ffprobe.exe"), "-v", "error", "-show_entries",
                                "format=duration", "-of", "csv=p=0", str(path)],
                               capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout or 0)
    out = []
    for k in range(n):
        r = subprocess.run([FF, "-v", "error", "-ss", f"{dur * (0.2 + 0.6 * k / max(1, n - 1)):.2f}", "-i", str(path),
                            "-frames:v", "1", "-vf", "scale=360:-2", "-f", "image2pipe", "-vcodec", "png", "-"],
                           capture_output=True, stdin=subprocess.DEVNULL)
        if r.stdout:
            out.append(Image.open(io.BytesIO(r.stdout)).convert("RGB"))
    return out


def video_height(path: Path) -> int:
    out = subprocess.run([FF.replace("ffmpeg.exe", "ffprobe.exe"), "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=height", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout.strip()
    return int(out) if out.isdigit() else 0


def hls_inputs(master: str) -> list[str]:
    """Аргументы ffmpeg: вариант с наибольшим RESOLUTION из master m3u8 (+ аудио-плейлист)."""
    base = master.rsplit("/", 1)[0] + "/"
    text = httpx.get(master, headers={"User-Agent": HTML_HEADERS["User-Agent"],
                                      "Referer": "https://www.pinterest.com/"}, timeout=30).text
    lines = text.splitlines()
    variants = [(int(re.search(r"RESOLUTION=\d+x(\d+)", ln).group(1)), lines[i + 1].strip())
                for i, ln in enumerate(lines) if ln.startswith("#EXT-X-STREAM-INF") and "RESOLUTION=" in ln]
    audio = re.search(r'#EXT-X-MEDIA:TYPE=AUDIO.*URI="([^"]+)"', text)
    if not variants:
        return ["-i", master]
    args = ["-i", base + max(variants)[1]]
    if audio:
        args += ["-i", base + audio.group(1), "-map", "0:v", "-map", "1:a"]
    return args


def dhash(im: Image.Image) -> int:
    g = np.asarray(im.convert("L").resize((9, 8)), dtype=np.int16)
    return int("".join("1" if b else "0" for b in (g[:, 1:] > g[:, :-1]).flatten()), 2)


def rank(pins: list[Pin]) -> None:
    """Итог = z(похожесть на реф) + z(на описание) − z(на анти-описание) по текущему набору."""
    a = np.array([p.parts for p in pins], dtype=np.float64)
    z = (a - a.mean(0)) / (a.std(0) + 1e-9)
    for p, (zi, zp, zn) in zip(pins, z):
        p.score = float(zi + zp - zn)


def download(c: dict, dest: Path) -> None:
    r = httpx.get(c["mp4"], headers={"User-Agent": HTML_HEADERS["User-Agent"],
                                      "Referer": "https://www.pinterest.com/"}, timeout=120)
    if r.status_code == 200:
        dest.write_bytes(r.content)
    # нет 720p mp4 или он на деле мелкий (бывает 234×416) — HLS: самый крупный вариант + звук
    if r.status_code != 200 or video_height(dest) < 700:
        subprocess.run([FF, "-v", "error", "-y", *hls_inputs(c["hls"]), "-c", "copy", str(dest)],
                       stdin=subprocess.DEVNULL, check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=sorted(PROFILES), required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--pick", help="номера с листа через запятую — скачать")
    ap.add_argument("--like", type=Path, help="папка отобранных видео: искать ещё похожих на них")
    ap.add_argument("--queries", help="свои запросы через | (вместо запросов профиля)")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    prof = PROFILES[args.profile]
    args.out.mkdir(parents=True, exist_ok=True)
    work = args.out / "_work"
    work.mkdir(exist_ok=True)

    if args.pick:
        cands = json.loads((args.out / "_candidates.json").read_text(encoding="utf-8"))
        for k, num in enumerate([int(x) for x in args.pick.split(",")], 1):
            c = cands[num - 1]
            dest = args.out / f"{k:02d}_{c['id']}.mp4"
            download(c, dest)
            print(f"{dest.name}  {c['dur']:.1f} с  {video_height(dest)}p  {dest.stat().st_size // 1024} KB",
                  flush=True)
        return 0

    from core.taste_embedder import get_embedder
    emb = get_embedder()
    ref_imgs = [Image.open(p).convert("RGB") for p in prof["refs"]] + [ref_frame(t, work) for t in prof["ref_t"]]
    seeds: list[str] = []
    seen: set[str] = set()
    if args.like:  # эталон — кадры отобранных видео; уже виденное не показываем
        liked = sorted(args.like.glob("*.mp4"))
        ref_imgs = [im for v in liked for im in local_frames(v)]
        seeds = [v.stem.split("_", 1)[1] for v in liked if v.stem.split("_", 1)[1].isdigit()]
        seen = {v.stem.split("_", 1)[1] for v in liked}
        sheet_json = args.like / "_candidates.json"
        if sheet_json.exists():
            seen |= {c["id"] for c in json.loads(sheet_json.read_text(encoding="utf-8"))}
        print(f"[like] эталонов {len(ref_imgs)} кадров из {len(liked)} видео, пропускаем {len(seen)} виденных",
              flush=True)
    ref_v = emb.embed_images(ref_imgs)
    pos_v, neg_v = emb.embed_texts(prof["texts"]), emb.embed_texts(prof["neg"])

    def parts(imgs: list[Image.Image]) -> tuple[np.ndarray, np.ndarray]:
        v = emb.embed_images(imgs)
        return np.stack([(v @ ref_v.T).max(1), (v @ pos_v.T).mean(1), (v @ neg_v.T).max(1)], 1), v

    cl = Client()
    pins: dict[str, Pin] = {}
    for sid in seeds:
        new = 0
        for obj in cl.related(sid):
            p = usable(obj, prof["ban"])
            if p and p.id not in pins and p.id not in seen:
                p.found_by, pins[p.id] = f"related:{sid}", p
                new += 1
        print(f"[like] похожие на {sid}: +{new}", flush=True)
    for q in (args.queries.split("|") if args.queries else prof["queries"]):
        new = 0
        for obj in cl.search(q, PAGES):
            p = usable(obj, prof["ban"])
            if p and p.id not in pins and p.id not in seen:
                p.found_by, pins[p.id] = q, p
                new += 1
        print(f"[search] {q!r}: +{new} (всего {len(pins)})", flush=True)

    def score_thumbs(ps: list[Pin]) -> None:
        ims, ok = [], []
        for p in ps:
            try:
                r = cl.cli.get(p.thumb, timeout=30)
                ims.append(Image.open(io.BytesIO(r.content)).convert("RGB"))
                ok.append(p)
            except Exception:
                pass
        if ims:
            for p, row in zip(ok, parts(ims)[0]):
                p.parts = tuple(float(x) for x in row)

    score_thumbs(list(pins.values()))
    rank(list(pins.values()))
    # похожие пины от лучших 8 → ещё кандидаты
    for p in sorted(pins.values(), key=lambda x: -x.score)[:8]:
        new = []
        for obj in cl.related(p.id):
            q = usable(obj, prof["ban"])
            if q and q.id not in pins and q.id not in seen:
                q.found_by, pins[q.id] = f"related:{p.id}", q
                new.append(q)
        score_thumbs(new)
        print(f"[related] {p.id}: +{len(new)}", flush=True)
    rank(list(pins.values()))

    # кадры по лучшим превью → монтаж, текст, итоговая оценка
    top = sorted(pins.values(), key=lambda x: -x.score)[:TOP_FRAMES]
    with ThreadPoolExecutor(6) as ex:
        fr = dict(zip([p.id for p in top], ex.map(lambda p: frames(p, work), top)))
    top = [p for p in top if len(fr[p.id]) >= 2]
    for p in top:
        pr, v = parts(fr[p.id])
        p.parts = tuple(float(x) for x in pr.mean(0))
        p.cont = float(min((v[i] @ v[i + 1]) for i in range(len(v) - 1)))
    montage = [p for p in top if p.cont < CONT_MIN]
    top = [p for p in top if p.cont >= CONT_MIN]
    print(f"[filter] монтаж из разных планов: −{len(montage)}", flush=True)
    rank(top)

    ocr = None
    if prof["ocr_max"] is not None:
        import easyocr
        ocr = easyocr.Reader(["en"], gpu=True, verbose=False)

    def has_text(ims: list[Image.Image]) -> bool:
        for im in ims[1:3]:
            res = ocr.readtext(np.asarray(im), detail=1)
            if sum(len(t.strip()) for _b, t, conf in res if conf >= 0.45) > prof["ocr_max"]:
                return True
        return False

    import cv2
    cascades = [cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / n)) for n in
                ("haarcascade_frontalface_default.xml", "haarcascade_profileface.xml")]

    def has_face(ims: list[Image.Image]) -> bool:
        for im in ims:
            g = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2GRAY)
            mn = max(40, g.shape[1] // 8)
            for cc in cascades:
                for img in (g, cv2.flip(g, 1)):
                    if len(cc.detectMultiScale(img, 1.1, 6, minSize=(mn, mn))):
                        return True
        return False

    seen: list[int] = []
    picked, n_text, n_face = [], 0, 0
    for p in sorted(top, key=lambda x: -x.score):
        ims = fr[p.id]
        h = dhash(ims[len(ims) // 2])
        if any(bin(h ^ s).count("1") <= 6 for s in seen):
            continue  # перезалив того же видео
        if prof.get("no_face") and has_face(ims):
            n_face += 1
            continue
        if ocr and has_text(ims):
            n_text += 1
            continue
        seen.append(h)
        picked.append(p)
        if len(picked) >= SHEET_N:
            break
    print(f"[filter] текст поверх кадра: −{n_text}, лица: −{n_face}", flush=True)

    font = ImageFont.truetype("arial.ttf", 22)
    FW, FH, COLS = 120, 213, 4
    rows = (len(picked) + COLS - 1) // COLS
    sheet = Image.new("RGB", (COLS * (FW * N_FRAMES + 10), rows * (FH + 6)), "white")
    d = ImageDraw.Draw(sheet)
    for i, p in enumerate(picked):
        x0, y0 = (i % COLS) * (FW * N_FRAMES + 10), (i // COLS) * (FH + 6)
        for j, im in enumerate(fr[p.id]):
            sheet.paste(ImageOps.fit(im, (FW, FH)), (x0 + j * FW, y0))
        d.rectangle([x0, y0, x0 + 110, y0 + 26], fill="black")
        d.text((x0 + 4, y0 + 1), f"{i + 1} · {p.dur:.0f}s", fill="yellow", font=font)
    sheet.save(args.out / "_candidates.jpg", quality=88)
    (args.out / "_candidates.json").write_text(json.dumps(
        [{"n": i + 1, "id": p.id, "score": round(p.score, 3), "cont": round(p.cont, 3), "dur": p.dur,
          "w": p.w, "h": p.h, "title": p.title, "found_by": p.found_by, "mp4": p.mp4, "hls": p.hls}
         for i, p in enumerate(picked)], indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"кандидатов {len(pins)} → лист {len(picked)}: {args.out / '_candidates.jpg'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
