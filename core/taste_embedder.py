#!/usr/bin/env python3
"""
Локальные визуальные эмбеддинги для клона вкуса.

SigLIP google/siglip-base-patch16-224 (768), fallback CLIP
openai/clip-vit-base-patch32 (512). GPU fp16 если есть CUDA, иначе CPU.
Модель в eval + torch.no_grad(), чтобы удерживаться примерно до 1 ГБ VRAM.
"""

from __future__ import annotations

import threading
from typing import Any

import numpy as np
from PIL import Image

SIGLIP_ID = "google/siglip-base-patch16-224"
CLIP_ID = "openai/clip-vit-base-patch32"
EMBED_BATCH = 32  # GPU-батч; на CPU тоже ок, меньше round-trips

_LOCK = threading.Lock()
_EMBEDDER: TasteEmbedder | None = None


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
        except Exception:
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
        try:
            model = AutoModel.from_pretrained(
                model_id,
                dtype=dtype,
                low_cpu_mem_usage=True,
            )
        except TypeError:
            model = AutoModel.from_pretrained(
                model_id,
                torch_dtype=dtype,
                low_cpu_mem_usage=True,
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
        dev_name = (
            torch.cuda.get_device_name(0) if cuda else "cpu"
        )
        print(
            f"[SigLIP] backend={model_id} device={self.device} "
            f"dtype={'fp16' if cuda else 'fp32'} gpu={dev_name}"
        )
        if cuda:
            torch.cuda.empty_cache()
            # sanity: первый параметр на cuda
            try:
                p0 = next(model.parameters())
                assert p0.is_cuda, "SigLIP не на CUDA после .cuda()"
            except StopIteration:
                pass

    def embed_images(self, pil_images: list[Image.Image]) -> np.ndarray:
        """L2-нормализованные векторы, shape (N, 512) или (N, 768)."""
        if not pil_images:
            width = self.dim or 768
            return np.zeros((0, width), dtype=np.float32)

        with _LOCK:
            if self._model is None:
                self._load(None)
            torch = self._torch
            rows: list[np.ndarray] = []
            images = [img.convert("RGB") for img in pil_images]
            for start in range(0, len(images), EMBED_BATCH):
                batch = images[start : start + EMBED_BATCH]
                rows.append(self._embed_batch(batch, torch))
            out = np.concatenate(rows, axis=0)
            self.dim = int(out.shape[1])
            return out

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        """L2-нормализованные текстовые эмбеддинги (тот же dim, что у картинок)."""
        clean = [str(t or "").strip() or "photo" for t in texts]
        if not clean:
            width = self.dim or 768
            return np.zeros((0, width), dtype=np.float32)

        with _LOCK:
            if self._model is None:
                self._load(None)
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
        i_vec = self.embed_images([image.convert("RGB")])[0]
        cos = float(np.dot(t_vec, i_vec))
        return float(self._cosine_to_prob(np.array([cos]))[0])

    def compute_text_image_relevances(
        self, slide_text: str, images: list[Image.Image]
    ) -> list[float]:
        """Пакетный text↔image score для списка картинок (один text embed)."""
        if not images:
            return []
        text = (slide_text or "").strip() or "lifestyle photo"
        t_vec = self.embed_texts([text])[0]
        i_mat = self.embed_images([im.convert("RGB") for im in images])
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
