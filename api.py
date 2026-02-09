from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import sqlite3

from fastapi import FastAPI, File, HTTPException, UploadFile

from fingerprinter import Fingerprinter
from matcher import find_best_match
from storage import init_db, insert_song

app = FastAPI(title="Audio Fingerprinting API")

DB_PATH = Path("fingerprints.db")
FINGERPRINTER = Fingerprinter()

init_db(DB_PATH)


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
) -> dict:
    tmp_path = _save_upload_to_temp(file)
    try:
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
    return {
        "match": {
            "song_id": song_id,
            "timestamp_seconds": timestamp,
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
def delete_song(song_id: int) -> dict:
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
