from __future__ import annotations

import sqlite3
from pathlib import Path

from fingerprinter import Fingerprinter, fingerprint_hash, load_wav_mono


def init_db(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS songs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                length_seconds REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fingerprints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hash INTEGER NOT NULL,
                t_anchor REAL NOT NULL,
                song_id INTEGER NOT NULL,
                FOREIGN KEY (song_id) REFERENCES songs(id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_fingerprints_hash ON fingerprints(hash)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_fingerprints_song ON fingerprints(song_id)"
        )


def append_fingerprints_to_db(
    wav_path: Path,
    db_path: Path,
    fingerprinter: Fingerprinter | None = None,
    song_id: str | None = None,
) -> int:
    init_db(db_path)
    fp = fingerprinter or Fingerprinter()
    fingerprints, trim_offset_seconds = fp.fingerprints_from_wav(wav_path)

    config = fp.config
    hop_len = config.nperseg - config.noverlap
    if hop_len <= 0:
        raise ValueError("Invalid hop length; noverlap must be < nperseg.")

    song_key = song_id or wav_path.stem
    sample_rate, mono = load_wav_mono(wav_path)
    length_seconds = mono.size / sample_rate if sample_rate > 0 else None

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO songs (name, length_seconds)
            VALUES (?, ?)
            ON CONFLICT(name) DO UPDATE SET length_seconds=excluded.length_seconds
            """,
            (song_key, length_seconds),
        )
        cur = conn.execute("SELECT id FROM songs WHERE name = ?", (song_key,))
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("Failed to fetch song id after insert.")
        song_row_id = row[0]

        rows = []
        for item in fingerprints:
            h = fingerprint_hash(item)
            t_anchor = trim_offset_seconds + (item.t1 * hop_len / config.target_rate)
            rows.append((h, t_anchor, song_row_id))

        conn.executemany(
            "INSERT INTO fingerprints (hash, t_anchor, song_id) VALUES (?, ?, ?)",
            rows,
        )
    return len(fingerprints)


def insert_song(
    wav_path: Path,
    db_path: Path,
    fingerprinter: Fingerprinter | None = None,
    song_id: str | None = None,
) -> int:
    if not wav_path.exists():
        raise FileNotFoundError(
            f"Missing WAV file at {wav_path.resolve()} - update wav_path."
        )
    return append_fingerprints_to_db(
        wav_path=wav_path,
        db_path=db_path,
        fingerprinter=fingerprinter,
        song_id=song_id,
    )
