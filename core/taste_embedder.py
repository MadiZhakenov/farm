#!/usr/bin/env python3
"""
Локальные визуальные эмбеддинги для клона вкуса.

SigLIP google/siglip-base-patch16-224 (768), fallback CLIP
openai/clip-vit-base-patch32 (512). GPU fp16 если есть CUDA, иначе CPU.
Модель в eval + torch.no_grad(), чтобы удерживаться примерно до 1 ГБ VRAM.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

SIGLIP_ID = "google/siglip-base-patch16-224"
CLIP_ID = "openai/clip-vit-base-patch32"
EMBED_BATCH = 32  # GPU-батч; на CPU тоже ок, меньше round-trips
# pin_id → L2 vector. Same photo scored by UGC/taste/rel/dedupe once.
EMBED_CACHE_MAX = 4096
# Cross-run disk cache (same pin_id → free embed, no quality change)
_DISK_CACHE_DIR = (
    Path(__file__).resolve().parent.parent / "data" / "cache" / "siglip_img"
)

_LOCK = threading.Lock()
_EMBEDDER: TasteEmbedder | None = None
_IMG_VEC_CACHE: "OrderedDict[str, np.ndarray]" | None = None
_CACHE_HITS = 0
_CACHE_MISSES = 0
# Фиксированные промпты (gender/face/hair/UGC-якоря) зовутся на каждый кадр —
# один text forward на строку за процесс вместо сотен.
_TEXT_VEC_CACHE: "OrderedDict[tuple[str, str], np.ndarray]" = OrderedDict()
TEXT_CACHE_MAX = 2048
# Кадры без pin_id (gender/face/attr-гейты) — ключ в памяти, не на диск
_MEM_KEY_PREFIX = "mem:"
_IMG_KEY_ATTR = "_farm_vec_key"


def _rgb(im: Image.Image) -> Image.Image:
    """convert('RGB') без копии, если кадр уже RGB (копия теряет кэш-ключ)."""
    return im if im.mode == "RGB" else im.convert("RGB")


def _implicit_key(im: Image.Image) -> str:
    """pin_id, которым кадр уже встречался, иначе хэш пикселей (только память)."""
    key = getattr(im, _IMG_KEY_ATTR, None)
    if key:
        return str(key)
    digest = hashlib.blake2b(_rgb(im).tobytes(), digest_size=16).hexdigest()
    key = f"{_MEM_KEY_PREFIX}{im.size[0]}x{im.size[1]}:{digest}"
    try:
        setattr(im, _IMG_KEY_ATTR, key)
    except Exception:
        pass
    return key


def _cache() -> "OrderedDict[str, np.ndarray]":
    global _IMG_VEC_CACHE
    if _IMG_VEC_CACHE is None:
        from collections import OrderedDict

        _IMG_VEC_CACHE = OrderedDict()
    return _IMG_VEC_CACHE


def clear_embed_cache() -> None:
    global _CACHE_HITS, _CACHE_MISSES
    with _LOCK:
        c = _cache()
        c.clear()
        _CACHE_HITS = 0
        _CACHE_MISSES = 0


def _disk_path(key: str) -> Path:
    safe = "".join(ch for ch in key if ch.isalnum() or ch in "-_")[:80]
    return _DISK_CACHE_DIR / f"{safe}.npy"


def _disk_load(key: str) -> np.ndarray | None:
    try:
        p = _disk_path(key)
        if not p.is_file():
            return None
        arr = np.asarray(np.load(str(p)), dtype=np.float32).reshape(-1)
        if arr.size < 64 or not np.isfinite(arr).all():
            return None
        return arr
    except Exception:
        return None


def _disk_save(key: str, vec: np.ndarray) -> None:
    try:
        _DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        np.save(
            str(_disk_path(key)),
            np.asarray(vec, dtype=np.float32).reshape(-1),
        )
    except Exception:
        pass


def embed_cache_stats() -> dict[str, int]:
    with _LOCK:
        return {
            "size": len(_cache()),
            "hits": int(_CACHE_HITS),
            "misses": int(_CACHE_MISSES),
        }


def _norm_cache_key(key: str | None) -> str | None:
    k = (key or "").strip()
    if not k or k.lower() in {"none", "null"}:
        return None
    # fake scrape ids — don't cache (unstable junk)
    if len(k) <= 6 and k.lower().startswith("img"):
        return None
    return k


def _feature_tensor(out: Any, torch: Any):
    """Достаёт матрицу (batch, dim) из тензора или ModelOutput transformers 4/5."""
    feats = None
    if torch.is_tensor(out):
        feats = out
    elif hasattr(out, "pooler_output") and out.pooler_output is not None:
        feats = out.pooler_output
    elif hasattr(out, "image_embeds") and out.image_embeds is not None:
        feats = out.image_embeds
    elif isinstance(out, (tuple, list)) and out:
        feats = out[1] if len(out) > 1 and out[1] is not None else out[0]
    if feats is None or not torch.is_tensor(feats):
        raise RuntimeError(f"неизвестный выход эмбеддера: {type(out).__name__}")
    if feats.ndim == 3:
        feats = feats[:, 0]
    if feats.ndim != 2:
        raise RuntimeError(f"ожидалась матрица эмбеддингов, получено {tuple(feats.shape)}")
    return feats


class TasteEmbedder:
    """Ленивая загрузка SigLIP, при сбое — CLIP."""

    def __init__(self) -> None:
        self.backend_id = ""
        self.device = "cpu"
        self.dim = 0
        self.attn_impl = "eager"
        self._model: Any = None
        self._processor: Any = None
        self._dtype: Any = None
        self._torch: Any = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def ensure(self, model_id: str | None = None) -> str:
        """Грузит модель один раз. model_id фиксирует бэкенд обученного фильтра."""
        with _LOCK:
            self._load(model_id)
            return self.backend_id

    def _load(self, model_id: str | None) -> None:
        target = model_id or SIGLIP_ID
        if self._model is not None and self.backend_id == target:
            return
        if model_id:
            self._load_id(model_id)
            return
        try:
            self._load_id(SIGLIP_ID)
        except Exception as exc:
            # Раньше молча уходили на CLIP — и модели вкуса/живости (обучены на
            # SigLIP) тихо переставали работать. Теперь причина видна в логе.
            print(
                f"[WARNING] SigLIP не загрузился: {type(exc).__name__}: {exc}\n"
                "[WARNING] Перехожу на запасной CLIP — модели вкуса и «живости» "
                "работать НЕ будут. Обычно помогает install.bat "
                "(ставит sentencepiece)."
            )
            self._model = None
            self._processor = None
            self._load_id(CLIP_ID)

    def _load_id(self, model_id: str) -> None:
        import torch
        from transformers import AutoModel, AutoProcessor
        from transformers.utils import logging as hf_logging

        hf_logging.disable_progress_bar()
        self._torch = torch
        cuda = bool(torch.cuda.is_available())
        if not cuda:
            print(
                "[WARNING] SigLIP: CUDA недоступна — работа на CPU "
                "(медленно). Установите CUDA-сборку torch."
            )
        self.device = "cuda" if cuda else "cpu"
        dtype = torch.float16 if cuda else torch.float32
        self._dtype = dtype

        try:
            processor = AutoProcessor.from_pretrained(model_id, use_fast=True)
        except TypeError:
            processor = AutoProcessor.from_pretrained(model_id)

        # Faster attention when CUDA: flash_attention_2 (needs flash-attn) →
        # sdpa (PyTorch built-in) → eager. Same weights; embeddings stay close.
        attn_candidates: list[str | None]
        if cuda:
            attn_candidates = ["flash_attention_2", "sdpa", None]
        else:
            attn_candidates = [None]

        model = None
        attn_used = "eager"
        last_err: Exception | None = None
        for attn in attn_candidates:
            kwargs: dict[str, Any] = {"low_cpu_mem_usage": True}
            if attn is not None:
                kwargs["attn_implementation"] = attn
            try:
                try:
                    model = AutoModel.from_pretrained(
                        model_id, dtype=dtype, **kwargs
                    )
                except TypeError:
                    model = AutoModel.from_pretrained(
                        model_id, torch_dtype=dtype, **kwargs
                    )
                attn_used = attn or "eager"
                break
            except Exception as exc:
                last_err = exc
                model = None
                continue
        if model is None:
            raise RuntimeError(
                f"SigLIP load failed ({model_id}): {last_err}"
            )

        model = model.to(self.device)
        # Жёстко: если CUDA есть — модель обязана быть на cuda
        if cuda:
            model = model.cuda()
            # параметры в fp16
            model = model.half() if hasattr(model, "half") else model
        model.eval()
        for param in model.parameters():
            param.requires_grad_(False)

        self._processor = processor
        self._model = model
        self.backend_id = model_id
        self.attn_impl = attn_used
        dev_name = (
            torch.cuda.get_device_name(0) if cuda else "cpu"
        )
        print(
            f"[SigLIP] backend={model_id} device={self.device} "
            f"attn={attn_used} dtype={'fp16' if cuda else 'fp32'} "
            f"gpu={dev_name}"
        )
        if cuda:
            torch.cuda.empty_cache()
            # sanity: первый параметр на cuda
            try:
                p0 = next(model.parameters())
                assert p0.is_cuda, "SigLIP не на CUDA после .cuda()"
            except StopIteration:
                pass

    def embed_images(
        self,
        pil_images: list[Image.Image],
        cache_keys: list[str | None] | None = None,
    ) -> np.ndarray:
        """
        L2-нормализованные векторы, shape (N, 512) или (N, 768).

        cache_keys: optional pin_id per image — hit skips GPU. Same photo
        reused by UGC / taste / relevance / dedupe without re-compute.
        """
        global _CACHE_HITS, _CACHE_MISSES
        if not pil_images:
            width = self.dim or 768
            return np.zeros((0, width), dtype=np.float32)

        keys: list[str | None]
        if cache_keys is None:
            keys = [None] * len(pil_images)
        else:
            if len(cache_keys) != len(pil_images):
                raise ValueError("cache_keys length must match images")
            keys = [_norm_cache_key(k) for k in cache_keys]
        # Кадр с pin_id запоминает ключ; гейты без ключа (gender/face/attr)
        # потом попадают в тот же вектор, а не гоняют SigLIP заново.
        for i, im in enumerate(pil_images):
            if keys[i]:
                if not getattr(im, _IMG_KEY_ATTR, None):
                    try:
                        setattr(im, _IMG_KEY_ATTR, keys[i])
                    except Exception:
                        pass
            else:
                keys[i] = _implicit_key(im)

        n = len(pil_images)
        out_rows: list[np.ndarray | None] = [None] * n
        miss_imgs: list[Image.Image] = []
        miss_idx: list[int] = []
        miss_keys: list[str | None] = []
        # Same pin twice in one call → one GPU forward, copy vec
        pending_key_slot: dict[str, int] = {}
        alias_to_miss: dict[int, int] = {}

        with _LOCK:
            if self._model is None:
                self._load(None)
            cache = _cache()
            for i, (im, key) in enumerate(zip(pil_images, keys)):
                if key and key in cache:
                    cache.move_to_end(key)
                    out_rows[i] = cache[key]
                    _CACHE_HITS += 1
                elif key and key in pending_key_slot:
                    alias_to_miss[i] = pending_key_slot[key]
                    _CACHE_HITS += 1
                else:
                    disk_hit = None
                    if key and not key.startswith(_MEM_KEY_PREFIX):
                        disk_hit = _disk_load(key)
                    if disk_hit is not None:
                        cache[key] = disk_hit
                        cache.move_to_end(key)
                        while len(cache) > EMBED_CACHE_MAX:
                            cache.popitem(last=False)
                        out_rows[i] = disk_hit
                        _CACHE_HITS += 1
                    else:
                        slot = len(miss_imgs)
                        miss_imgs.append(im)
                        miss_idx.append(i)
                        miss_keys.append(key)
                        if key:
                            pending_key_slot[key] = slot
                        _CACHE_MISSES += 1

            if miss_imgs:
                torch = self._torch
                rows: list[np.ndarray] = []
                for start in range(0, len(miss_imgs), EMBED_BATCH):
                    batch = [
                        img.convert("RGB")
                        for img in miss_imgs[start : start + EMBED_BATCH]
                    ]
                    rows.append(self._embed_batch(batch, torch))
                    del batch
                computed = np.concatenate(rows, axis=0)
                self.dim = int(computed.shape[1])
                for j, (idx, key) in enumerate(zip(miss_idx, miss_keys)):
                    vec = np.asarray(computed[j], dtype=np.float32).reshape(-1).copy()
                    out_rows[idx] = vec
                    if key:
                        cache[key] = vec
                        cache.move_to_end(key)
                        while len(cache) > EMBED_CACHE_MAX:
                            cache.popitem(last=False)
                        if not key.startswith(_MEM_KEY_PREFIX):
                            _disk_save(key, vec)
                for img_i, miss_j in alias_to_miss.items():
                    out_rows[img_i] = out_rows[miss_idx[miss_j]]
            elif self.dim <= 0 and out_rows and out_rows[0] is not None:
                self.dim = int(out_rows[0].shape[0])

        return np.stack([r for r in out_rows if r is not None], axis=0)

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        """L2-нормализованные текстовые эмбеддинги (тот же dim, что у картинок)."""
        clean = [str(t or "").strip() or "photo" for t in texts]
        if not clean:
            width = self.dim or 768
            return np.zeros((0, width), dtype=np.float32)

        with _LOCK:
            if self._model is None:
                self._load(None)
            found: dict[str, np.ndarray] = {}
            missing: list[str] = []
            for t in dict.fromkeys(clean):
                vec = _TEXT_VEC_CACHE.get((self.backend_id, t))
                if vec is None:
                    missing.append(t)
                else:
                    _TEXT_VEC_CACHE.move_to_end((self.backend_id, t))
                    found[t] = vec
            if missing:
                arr = self._embed_texts_uncached(missing)
                for t, vec in zip(missing, arr):
                    found[t] = vec
                    _TEXT_VEC_CACHE[(self.backend_id, t)] = vec
                    while len(_TEXT_VEC_CACHE) > TEXT_CACHE_MAX:
                        _TEXT_VEC_CACHE.popitem(last=False)
            return np.stack([found[t] for t in clean], axis=0)

    def _embed_texts_uncached(self, clean: list[str]) -> np.ndarray:
        """Один text forward (вызывать под _LOCK)."""
        torch = self._torch
        # SigLIP: padding="max_length"; CLIP: обычный padding
        try:
            inputs = self._processor(
                text=clean,
                padding="max_length",
                truncation=True,
                return_tensors="pt",
            )
        except Exception:
            inputs = self._processor(
                text=clean,
                padding=True,
                truncation=True,
                return_tensors="pt",
            )
        inputs = {
            k: v.to(self.device) if torch.is_tensor(v) else v
            for k, v in inputs.items()
            if k in ("input_ids", "attention_mask")
        }
        with torch.no_grad():
            raw = self._model.get_text_features(**inputs)
            feats = _feature_tensor(raw, torch).float()
            feats = feats / feats.norm(p=2, dim=-1, keepdim=True).clamp_min(1e-6)
        arr = feats.detach().cpu().numpy().astype(np.float32, copy=False)
        if not np.isfinite(arr).all():
            raise RuntimeError("текстовые эмбеддинги содержат NaN/Inf")
        self.dim = int(arr.shape[1])
        return arr

    def _cosine_to_prob(self, cosines: np.ndarray) -> np.ndarray:
        """
        SigLIP: P = sigmoid(cos * exp(logit_scale) + logit_bias).
        Сырой cosine ~0.12 → ~0.7+ для match; mismatch уходит к ~0.
        CLIP без bias: clip(cos, 0, 1).
        """
        cos = np.asarray(cosines, dtype=np.float64)
        scale = getattr(self._model, "logit_scale", None)
        bias = getattr(self._model, "logit_bias", None)
        if scale is None:
            return np.clip(cos, 0.0, 1.0).astype(np.float32)
        try:
            s = float(scale.exp().detach().cpu().item())
        except Exception:
            s = float(np.exp(float(scale.detach().cpu().item())))
        b = 0.0
        if bias is not None:
            try:
                b = float(bias.detach().cpu().item())
            except Exception:
                b = float(bias)
        logits = cos * s + b
        # численно стабильный sigmoid
        probs = np.where(
            logits >= 0,
            1.0 / (1.0 + np.exp(-logits)),
            np.exp(logits) / (1.0 + np.exp(logits)),
        )
        return np.clip(probs, 0.0, 1.0).astype(np.float32)

    def compute_text_image_relevance(
        self, slide_text: str, image: Image.Image
    ) -> float:
        """
        SigLIP text↔image relevance ∈ [0, 1] (sigmoid logits).
        Локально, torch.no_grad(), без API.
        """
        text = (slide_text or "").strip() or "lifestyle photo"
        t_vec = self.embed_texts([text])[0]
        i_vec = self.embed_images([_rgb(image)])[0]
        cos = float(np.dot(t_vec, i_vec))
        return float(self._cosine_to_prob(np.array([cos]))[0])

    def compute_text_image_relevances(
        self,
        slide_text: str,
        images: list[Image.Image],
        *,
        cache_keys: list[str | None] | None = None,
        image_vecs: np.ndarray | None = None,
    ) -> list[float]:
        """Пакетный text↔image score (один text embed; картинки с кэшем)."""
        if not images and image_vecs is None:
            return []
        text = (slide_text or "").strip() or "lifestyle photo"
        t_vec = self.embed_texts([text])[0]
        if image_vecs is None:
            i_mat = self.embed_images(
                [_rgb(im) for im in images],
                cache_keys=cache_keys,
            )
        else:
            i_mat = np.asarray(image_vecs, dtype=np.float32)
        sims = i_mat @ t_vec
        probs = self._cosine_to_prob(sims)
        return [float(p) for p in probs]

    def _embed_batch(self, batch: list[Image.Image], torch: Any) -> np.ndarray:
        inputs = self._processor(images=batch, return_tensors="pt")
        pixel_values = inputs["pixel_values"].to(device=self.device, dtype=self._dtype)
        with torch.no_grad():
            raw = self._model.get_image_features(pixel_values=pixel_values)
            feats = _feature_tensor(raw, torch).float()
            feats = feats / feats.norm(p=2, dim=-1, keepdim=True).clamp_min(1e-6)
        arr = feats.detach().cpu().numpy().astype(np.float32, copy=False)
        if not np.isfinite(arr).all():
            raise RuntimeError("эмбеддинги содержат NaN/Inf")
        return arr


def get_embedder() -> TasteEmbedder:
    global _EMBEDDER
    with _LOCK:
        if _EMBEDDER is None:
            _EMBEDDER = TasteEmbedder()
        return _EMBEDDER


def compute_text_image_relevance(slide_text: str, image: Image.Image) -> float:
    """Удобный вход: SigLIP text↔image relevance 0..1."""
    return get_embedder().compute_text_image_relevance(slide_text, image)
