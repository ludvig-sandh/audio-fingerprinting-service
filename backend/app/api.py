from __future__ import annotations

import logging
from pathlib import Path

import os

from fastapi import FastAPI, File, HTTPException, UploadFile, Header
from fastapi.middleware.cors import CORSMiddleware

from fingerprinter import AudioClip, Fingerprinter, load_wav_mono_bytes
from matcher import find_best_match
from storage import (
    SongAlreadyExistsError,
    count_songs_in_db,
    delete_song_by_id,
    init_db,
    insert_song,
    list_songs_from_db,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="Audio Fingerprinting API")

DB_PATH = Path(os.getenv("FP_DB_PATH", "fingerprints.db"))
FINGERPRINTER = Fingerprinter()

init_db(DB_PATH)

ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")
_max_songs_raw = os.getenv("MAX_SONGS")
MAX_SONGS = int(_max_songs_raw) if _max_songs_raw else None
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)



def _read_upload_bytes(upload: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large. Max size is {MAX_UPLOAD_BYTES} bytes.",
                )
            chunks.append(chunk)
    finally:
        upload.file.close()
    return b"".join(chunks)


def _load_upload_audio(upload: UploadFile) -> AudioClip:
    wav_bytes = _read_upload_bytes(upload)
    sample_rate, mono = load_wav_mono_bytes(wav_bytes)
    return AudioClip(sample_rate=sample_rate, mono=mono)


def _audio_duration_seconds(audio: AudioClip) -> float:
    return audio.duration_seconds()


def _validate_song_duration(audio: AudioClip) -> None:
    duration_seconds = _audio_duration_seconds(audio)
    if duration_seconds < 60:
        raise HTTPException(
            status_code=400,
            detail="Song is too short. Minimum length is 1 minute.",
        )
    if duration_seconds > 300:
        raise HTTPException(
            status_code=400,
            detail="Song is too long. Max length is 5 minutes.",
        )


def _validate_sample_duration(audio: AudioClip) -> float:
    recording_length = _audio_duration_seconds(audio)
    if recording_length > 15:
        raise HTTPException(
            status_code=400,
            detail="Sample is too long. Max length is 15 seconds.",
        )
    return recording_length


@app.post("/songs")
def insert_song_endpoint(
    file: UploadFile = File(...),
    song_name: str | None = None,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict:
    if not ADMIN_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="ADMIN_API_KEY is not configured.",
        )
    if x_api_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized.")

    try:
        audio = _load_upload_audio(file)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to read upload for /songs")
        raise HTTPException(
            status_code=400,
            detail="Invalid or unreadable uploaded audio file.",
        ) from exc

    try:
        if MAX_SONGS is not None:
            current_count = count_songs_in_db(db_path=DB_PATH)
            if current_count >= MAX_SONGS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Song limit reached ({MAX_SONGS}).",
                )

        _validate_song_duration(audio)

        name = song_name or Path(file.filename or "uploaded").stem
        song_id = insert_song(
            audio=audio,
            db_path=DB_PATH,
            fingerprinter=FINGERPRINTER,
            name=name,
        )
    except SongAlreadyExistsError:
        raise HTTPException(
            status_code=409,
            detail=f"Song '{name}' already exists.",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to process song insert for /songs")
        raise HTTPException(
            status_code=400,
            detail="Unable to process uploaded audio.",
        ) from exc

    return {"song_id": song_id, "song_name": name}


@app.post("/identify")
def identify_song_endpoint(
    file: UploadFile = File(...),
) -> dict:
    try:
        audio = _load_upload_audio(file)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to read upload for /identify")
        raise HTTPException(
            status_code=400,
            detail="Invalid or unreadable uploaded audio file.",
        ) from exc

    try:
        recording_length = _validate_sample_duration(audio)
        song_id, timestamp, certainty = find_best_match(
            audio=audio,
            db_path=DB_PATH,
            fingerprinter=FINGERPRINTER,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to process song identification for /identify")
        raise HTTPException(
            status_code=400,
            detail="Unable to process uploaded audio sample.",
        ) from exc

    if song_id is None:
        return {"match": None}

    adjusted_timestamp = int(round(timestamp + recording_length))
    return {
        "match": {
            "song_name": song_id,
            "timestamp_seconds": adjusted_timestamp,
            "certainty": certainty,
        }
    }


@app.get("/songs")
def list_songs() -> dict:
    if not DB_PATH.exists():
        return {"songs": []}

    songs = list_songs_from_db(db_path=DB_PATH)
    return {"songs": songs}


@app.delete("/songs/{song_id}")
def delete_song(
    song_id: int,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict:
    if not ADMIN_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="ADMIN_API_KEY is not configured.",
        )
    if x_api_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized.")
    if not DB_PATH.exists():
        raise HTTPException(status_code=404, detail="Database not found.")

    deleted = delete_song_by_id(song_id=song_id, db_path=DB_PATH)
    if not deleted:
        raise HTTPException(status_code=404, detail="Song not found.")

    return {"deleted_song_id": song_id}
