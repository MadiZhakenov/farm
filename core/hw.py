"""Один код на двух машинах: ПК с RTX 3070 и офисный ноутбук (Intel Core Ultra 5 125H, Arc, Quick Sync).

На машине с NVIDIA ничего не меняет. Без NVIDIA (ноутбук) каждая команда ffmpeg, написанная «под 3070», на лету
переводится (подмена subprocess.Popen — только для ffmpeg; включается при импорте core.gpu_ffmpeg):
  • h264_cuvid/hevc_cuvid + -crop/-resize в распаковщике → распаковка процессором + crop/scale первым фильтром
    этого входа (замер ноутбука 18.11: процессор 0,52 с, d3d11va 1,30 с — распаковывает процессор);
  • -hwaccel cuda, -hwaccel_device, -hwaccel_output_format, -init_hw_device, -filter_hw_device → убираются;
  • hwupload_cuda/hwdownload → null, overlay_cuda → overlay, scale_cuda → scale (+format);
  • h264_nvenc → h264_qsv (Quick Sync: 4 сборки сразу 468 к/с против libx264 286), -cq N → -global_quality N;
    нет Quick Sync — libx264 veryfast (-crf);
  • -filter_complex_script файл → -/filter_complex файл (ffmpeg 9 на ноутбуке не знает старый ключ).
torch: device() — cuda → xpu (Arc) → cpu; half() — половинная точность там, где есть видеокарта.

Принудительно: FARM_HW=nvidia (ничего не переводить) | intel (Quick Sync) | cpu (libx264) — так проверяется путь
ноутбука на ПК. FARM_TORCH=cuda|xpu|cpu — устройство torch.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

_CACHE: dict = {}


# ---------------- что есть на машине ----------------
def mode() -> str:
    """nvidia | intel | cpu — как собирать видео на этой машине."""
    if "mode" not in _CACHE:
        m = os.environ.get("FARM_HW", "").lower()
        if m not in ("nvidia", "intel", "cpu"):
            m = "nvidia" if _has_nvidia() else ("intel" if _has_qsv() else "cpu")
        elif m == "intel" and not _has_qsv():
            m = "cpu"
        _CACHE["mode"] = m
    return _CACHE["mode"]


def nvidia() -> bool:
    return mode() == "nvidia"


def _has_nvidia() -> bool:
    if not shutil.which("nvidia-smi"):
        return False
    try:
        r = _orig_popen_run(["nvidia-smi", "-L"])
        return r[0] == 0 and b"GPU" in r[1]
    except OSError:
        return False


def _has_qsv() -> bool:
    """Quick Sync реально кодирует (а не просто есть в списке кодеров)."""
    try:
        r = _orig_popen_run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=256x256:d=0.2:r=30",
                             "-c:v", "h264_qsv", "-global_quality", "27", "-f", "null", "-"])
        return r[0] == 0
    except OSError:
        return False


def device() -> str:
    """Устройство torch: cuda → xpu (Arc) → cpu (FARM_TORCH — принудительно)."""
    if "dev" not in _CACHE:
        want = os.environ.get("FARM_TORCH", "").lower()
        import torch
        if want in ("cuda", "xpu", "cpu"):
            dev = want
        elif torch.cuda.is_available():
            dev = "cuda"
        elif getattr(torch, "xpu", None) is not None and torch.xpu.is_available() and _xpu_ok():
            dev = "xpu"
        else:
            dev = "cpu"
        _CACHE["dev"] = dev
    return _CACHE["dev"]


def _xpu_ok() -> bool:
    """Arc тянет то, что нужно сборщикам (roi_align, half-матрицы, bicubic) — иначе считаем на процессоре."""
    try:
        import torch
        import torch.nn.functional as F
        from torchvision.ops import roi_align
        x = torch.rand(4, 1, 48, 27, device="xpu")
        b = torch.tensor([[0, 1.0, 1.0, 20.0, 40.0]], device="xpu")
        roi_align(x, b, (16, 17), spatial_scale=1.0, sampling_ratio=-1, aligned=True)
        F.interpolate(x, size=(96, 54), mode="bicubic", align_corners=False)
        h = torch.ones(8, 256, device="xpu", dtype=torch.half)
        (h @ h.T).sum().item()
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[hw] Arc (xpu) не подошёл — torch на процессоре: {e!r}"[:300], flush=True)
        return False


def half_ok() -> bool:
    return device() in ("cuda", "xpu")


def empty_cache() -> None:
    import torch
    d = device()
    if d == "cuda":
        torch.cuda.empty_cache()
    elif d == "xpu":
        torch.xpu.empty_cache()


# ---------------- перевод команды ffmpeg ----------------
NO_VALUE = {"-y", "-n", "-nostdin", "-hide_banner", "-an", "-vn", "-sn", "-dn", "-shortest", "-stats", "-nostats",
            "-re", "-copyts", "-start_at_zero", "-accurate_seek", "-noaccurate_seek", "-autorotate", "-noautorotate",
            "-benchmark", "-ignore_unknown", "-copy_unknown", "-xerror", "-print_graphs"}
DROP_PAIR = {"-hwaccel", "-hwaccel_device", "-hwaccel_output_format", "-init_hw_device", "-filter_hw_device",
             "-extra_hw_frames"}
NVENC_ONLY = {"-rc", "-tune", "-b_ref_mode", "-spatial-aq", "-spatial_aq", "-temporal-aq", "-temporal_aq",
              "-rc-lookahead", "-multipass", "-zerolatency", "-2pass", "-gpu", "-surfaces", "-aq-strength", "-nonref_p",
              "-strict_gop", "-weighted_pred", "-cbr", "-no-scenecut", "-forced-idr", "-delay"}
QSV_PRESET = {"p1": "veryfast", "p2": "veryfast", "p3": "faster", "p4": "fast", "p5": "medium", "p6": "slow",
              "p7": "slower", "fast": "fast", "medium": "medium", "slow": "slow", "hq": "medium", "hp": "veryfast",
              "default": "medium", "llhq": "fast", "ll": "veryfast", "llhp": "veryfast"}
X264_PRESET = {"p1": "ultrafast", "p2": "superfast", "p3": "veryfast", "p4": "veryfast", "p5": "veryfast",
               "p6": "faster", "p7": "fast"}


def is_ffmpeg(arg0) -> bool:
    n = Path(str(arg0)).name.lower()
    return n in ("ffmpeg", "ffmpeg.exe")


def _cuda_filters(g: str) -> str:
    """Фильтры видеокарты NVIDIA → обычные."""
    g = re.sub(r"\bhwupload_cuda\b(=[^,;\[]*)?", "null", g)
    g = re.sub(r"\bhwdownload\b(=[^,;\[]*)?", "null", g)
    g = re.sub(r"\boverlay_cuda\b", "overlay", g)

    def sc(m: re.Match) -> str:
        opts = (m.group(1) or "").lstrip("=")
        keep, fmt, pos = [], None, 0
        for o in [x for x in opts.split(":") if x]:
            k, _, v = o.partition("=")
            if not _:                                       # позиционные w:h
                if pos < 2:
                    keep.append(o)
                pos += 1
            elif k == "format":
                fmt = v
            elif k in ("w", "h", "width", "height", "force_original_aspect_ratio", "force_divisible_by"):
                keep.append(o)
        out = "scale" + ("=" + ":".join(keep) if keep else "")
        return out + (f",format={fmt}" if fmt else "")
    return re.sub(r"\bscale_cuda\b(=[^,;\[]*)?", sc, g)


def _prefix_graph(g: str, pre: dict[int, str]) -> str:
    """Обрезку/масштаб распаковщика (pre[вход]) — первым фильтром этого входа в графе."""
    heads = []
    for k, chain in sorted(pre.items()):
        lab = f"_hwin{k}"
        pat = re.compile(rf"\[{k}(:v(:0)?)?\]")
        if pat.search(g):
            g = pat.sub(f"[{lab}]", g)
            heads.append(f"[{k}:v]{chain}[{lab}]")
        elif k == 0 and not g.lstrip().startswith("["):   # граф без меток: первый вход сам идёт в первый фильтр
            g = f"{chain},{g}"
    return ";".join(heads + [g]) if heads else g


def _graph_file(path: str, pre: dict[int, str]) -> str:
    src = Path(path)
    g = _prefix_graph(_cuda_filters(src.read_text(encoding="utf-8")), pre)
    dst = src.with_name(src.stem + "_hw" + src.suffix)
    dst.write_text(g, encoding="utf-8")
    return str(dst)


def translate(cmd: list[str]) -> list[str]:
    """Команда ffmpeg «под 3070» → команда для машины без NVIDIA (см. описание модуля)."""
    m = mode()
    if m == "nvidia":
        return cmd
    args = [str(a) for a in cmd]
    out: list[str] = [args[0]]
    pre: dict[int, str] = {}                               # вход → crop/scale вместо cuvid -crop/-resize
    n_in = 0
    i = 1
    cur_in: dict = {}                                      # опции cuvid текущего (ещё не открытого) входа
    vf_at = None
    enc = "h264_qsv" if m == "intel" else "libx264"
    seen_nvenc = False
    while i < len(args):
        a = args[i]
        v = args[i + 1] if i + 1 < len(args) else None
        if a in DROP_PAIR:
            i += 2
            continue
        if a in ("-c:v", "-vcodec", "-codec:v") and v and v.endswith("_cuvid"):
            cur_in["cuvid"] = True
            i += 2
            continue
        if cur_in.get("cuvid") and a in ("-crop", "-resize", "-deint", "-drop_second_field", "-surfaces"):
            cur_in[a] = v
            i += 2
            continue
        if a == "-i":
            if cur_in.get("cuvid"):
                chain = []
                if cur_in.get("-crop"):
                    t, b, l, r = (int(x) for x in cur_in["-crop"].split("x"))
                    chain.append(f"crop=iw-{l + r}:ih-{t + b}:{l}:{t}")
                if cur_in.get("-resize"):
                    w, h = cur_in["-resize"].split("x")
                    chain.append(f"scale={w}:{h}:flags=bicubic,setsar=1")   # cuvid -resize: пиксель квадратный
                elif chain:
                    chain.append("setsar=1")
                if chain:
                    pre[n_in] = ",".join(chain)
            cur_in = {}
            out += [a, v]
            n_in += 1
            i += 2
            continue
        if a in ("-c:v", "-vcodec", "-codec:v", "-c:v:0") and v in ("h264_nvenc", "hevc_nvenc"):
            seen_nvenc = True
            if v == "hevc_nvenc":
                out += [a, "hevc_qsv" if m == "intel" else "libx265"]
            else:
                out += [a, enc]
            if m == "cpu":
                out += ["-pix_fmt", "yuv420p"]
            i += 2
            continue
        if a in ("-filter_complex", "-lavfi"):
            out += [a, _prefix_graph(_cuda_filters(v), pre)]
            pre = {}
            i += 2
            continue
        if a in ("-filter_complex_script", "-/filter_complex"):
            out += ["-/filter_complex", _graph_file(v, pre)]
            pre = {}
            i += 2
            continue
        if a in ("-vf", "-filter:v", "-filter:v:0"):
            chain = pre.pop(0, None)
            vf = _cuda_filters(v)
            out += [a, f"{chain},{vf}" if chain else vf]
            vf_at = len(out)
            i += 2
            continue
        if a in NO_VALUE or not a.startswith("-") or a == "-":
            if not a.startswith("-") or a == "-":          # выход: незабранная обрезка входа 0 → -vf перед ним
                if pre.get(0) and vf_at is None and n_in == 1:
                    out += ["-vf", pre.pop(0)]
            out.append(a)
            i += 1
            continue
        out += [a, v]
        i += 2
    if seen_nvenc:
        out = _encoder_opts(out, m)
    return out


def _encoder_opts(args: list[str], m: str) -> list[str]:
    """Опции NVENC → Quick Sync / libx264."""
    out, i = [], 0
    has_cq = "-cq" in args
    while i < len(args):
        a = args[i]
        v = args[i + 1] if i + 1 < len(args) else None
        if a in NVENC_ONLY and a not in ("-tune",):
            i += 2
            continue
        if a == "-tune" and v in ("hq", "ll", "ull", "lossless", "uhq"):
            i += 2
            continue
        if a == "-preset" and v is not None:
            out += [a, (QSV_PRESET if m == "intel" else X264_PRESET).get(v, v if m == "cpu" else "medium")]
            i += 2
            continue
        if a == "-cq" and v is not None:
            q = int(float(v))
            out += (["-global_quality", str(q)] if m == "intel" else ["-crf", str(max(0, q - 4))])
            i += 2
            continue
        if a == "-qp" and v is not None:
            out += (["-q:v", v] if m == "intel" else ["-qp", v])
            i += 2
            continue
        if a in ("-maxrate", "-bufsize") and m == "intel" and has_cq:   # ICQ: ограничение битрейта сменило бы режим
            i += 2
            continue
        out.append(a)
        i += 1
    return out


# ---------------- подмена Popen (только для ffmpeg) ----------------
_OrigPopen = subprocess.Popen


def _orig_popen_run(cmd: list[str]) -> tuple[int, bytes]:
    p = _OrigPopen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    o, _ = p.communicate(timeout=30)
    return p.returncode, o or b""


class _Popen(_OrigPopen):
    def __init__(self, args, *a, **kw):
        if isinstance(args, (list, tuple)) and args and is_ffmpeg(args[0]):
            args = translate(list(args))
        super().__init__(args, *a, **kw)


def install() -> str:
    """Включить перевод для этого процесса (на машине с NVIDIA — ничего не делает). Возвращает режим."""
    m = mode()
    if m != "nvidia" and subprocess.Popen is not _Popen:
        subprocess.Popen = _Popen
    return m
