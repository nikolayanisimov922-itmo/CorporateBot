"""Локальное распознавание речи (голосовые → текст) через faster-whisper.

Модель грузится один раз при первом голосовом (скачивается ~0.5 ГБ). Работает
на CPU сервера. Требует установленный ffmpeg (для декодирования .ogg).
"""
from __future__ import annotations

import logging
import os


class Transcriber:
    def __init__(self, model_size: str | None = None) -> None:
        self._model = None
        self._model_size = model_size or os.getenv("WHISPER_MODEL", "small")

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            logging.info("Загружаю модель распознавания речи (%s)…", self._model_size)
            self._model = WhisperModel(
                self._model_size, device="cpu", compute_type="int8"
            )
        return self._model

    def transcribe(self, audio_path: str) -> tuple[str, str]:
        """Возвращает (распознанный текст, код языка). Блокирующая операция."""
        model = self._load()
        segments, info = model.transcribe(audio_path, beam_size=5)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return text, (info.language or "")
