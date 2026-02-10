from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import os
import sqlite3

from fastapi import FastAPI, File, HTTPException, UploadFile, Header
from fastapi.middleware.cors import CORSMiddleware

from fingerprinter import Fingerprinter, load_wav_mono
from matcher import find_best_match
from storage import init_db, insert_song

app = FastAPI(title="Audio Fingerprinting API")

DB_PATH = Path(os.getenv("FP_DB_PATH", "fingerprints.db"))
FINGERPRINTER = Fingerprinter()

init_db(DB_PATH)

ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")
MAX_SONGS = int(os.getenv("MAX_SONGS", "100"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)



def _save_upload_to_temp(upload: UploadFile) -> Path:
    suffix = Path(upload.filename or "").suffix or ".wav"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        with tmp as f:
            shutil.copyfileobj(upload.file, f)
    finally:
        upload.file.close()
    return Path(tmp.name)

@app.post("/songs")
def insert_song_endpoint(
    file: UploadFile = File(...),
    song_id: str | None = None,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict:
    if not ADMIN_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="ADMIN_API_KEY is not configured.",
        )
    if x_api_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized.")
    tmp_path = _save_upload_to_temp(file)
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.execute("SELECT COUNT(*) FROM songs")
            current_count = cur.fetchone()[0]
            if current_count >= MAX_SONGS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Song limit reached ({MAX_SONGS}).",
                )
        sample_rate, mono = load_wav_mono(tmp_path)
        duration_seconds = mono.size / sample_rate if sample_rate > 0 else 0.0
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
        count = insert_song(
            wav_path=tmp_path,
            db_path=DB_PATH,
            fingerprinter=FINGERPRINTER,
            song_id=song_id or Path(file.filename or tmp_path.name).stem,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    return {"song_id": song_id or Path(file.filename or "").stem, "fingerprints": count}


@app.post("/identify")
def identify_song_endpoint(
    file: UploadFile = File(...),
) -> dict:
    tmp_path = _save_upload_to_temp(file)
    try:
        sample_rate, mono = load_wav_mono(tmp_path)
        recording_length = mono.size / sample_rate if sample_rate > 0 else 0.0
        if recording_length > 15:
            raise HTTPException(
                status_code=400,
                detail="Sample is too long. Max length is 15 seconds.",
            )
        song_id, timestamp, certainty = find_best_match(
            wav_path=tmp_path,
            db_path=DB_PATH,
            fingerprinter=FINGERPRINTER,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    if song_id is None:
        return {"match": None}

    adjusted_timestamp = timestamp + recording_length
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

    songs: list[dict] = []
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT id, name, length_seconds FROM songs ORDER BY name")
        for row in cur:
            songs.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "length_seconds": row["length_seconds"],
                }
            )
    return {"songs": songs}


@app.delete("/songs/{song_id}")
def delete_song(
    song_id: int,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict:
    print(ADMIN_API_KEY)
    if not ADMIN_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="ADMIN_API_KEY is not configured.",
        )
    if x_api_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized.")
    if not DB_PATH.exists():
        raise HTTPException(status_code=404, detail="Database not found.")

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("SELECT id FROM songs WHERE id = ?", (song_id,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Song not found.")

        conn.execute("DELETE FROM fingerprints WHERE song_id = ?", (song_id,))
        conn.execute("DELETE FROM songs WHERE id = ?", (song_id,))

    return {"deleted_song_id": song_id}
