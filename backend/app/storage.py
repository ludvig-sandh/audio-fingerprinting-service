from __future__ import annotations

import sqlite3
from pathlib import Path

from fingerprinter import AudioClip, Fingerprint, Fingerprinter, fingerprint_hash


class SongAlreadyExistsError(Exception):
    pass


def init_db(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS songs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                length_seconds REAL NOT NULL DEFAULT 0.0,
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


def _insert_song_and_get_id(conn: sqlite3.Connection, name: str, length_seconds: float) -> int:
    try:
        cur = conn.execute(
            "INSERT INTO songs (name, length_seconds) VALUES (?, ?)",
            (name, length_seconds),
        )
    except sqlite3.IntegrityError as exc:
        raise SongAlreadyExistsError(f"Song '{name}' already exists.") from exc
    return int(cur.lastrowid)


def _build_fingerprint_rows(
    fingerprints: list[Fingerprint],
    trim_offset_seconds: float,
    hop_len: int,
    target_rate: int,
    song_row_id: int,
) -> list[tuple[int, float, int]]:
    return [
        (
            fingerprint_hash(item),
            trim_offset_seconds + (item.t1 * hop_len / target_rate),
            song_row_id,
        )
        for item in fingerprints
    ]


def insert_song(
    audio: AudioClip,
    db_path: Path,
    name: str,
    fingerprinter: Fingerprinter | None = None,
) -> int:
    init_db(db_path)
    fp = fingerprinter or Fingerprinter()

    fingerprints, trim_offset_seconds = fp.fingerprints_from_audio(audio)

    config = fp.config
    hop_len = config.nperseg - config.noverlap
    length_seconds = audio.duration_seconds()

    with sqlite3.connect(db_path) as conn:
        song_row_id = _insert_song_and_get_id(conn, name, length_seconds)
        rows = _build_fingerprint_rows(
            fingerprints=fingerprints,
            trim_offset_seconds=trim_offset_seconds,
            hop_len=hop_len,
            target_rate=config.target_rate,
            song_row_id=song_row_id,
        )
        if rows:
            conn.executemany(
                "INSERT INTO fingerprints (hash, t_anchor, song_id) VALUES (?, ?, ?)",
                rows,
            )
            
    return song_row_id


def delete_song_by_id(song_id: int, db_path: Path) -> bool:
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute("SELECT id FROM songs WHERE id = ?", (song_id,))
        row = cur.fetchone()
        if row is None:
            return False

        conn.execute("DELETE FROM fingerprints WHERE song_id = ?", (song_id,))
        conn.execute("DELETE FROM songs WHERE id = ?", (song_id,))

    return True


def get_song_name_by_id(song_id: int, db_path: Path) -> str | None:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT name FROM songs WHERE id = ?", (song_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return str(row["name"])


def fetch_fingerprint_hits(
    db_path: Path,
    sample_hashes: list[tuple[int, float]],
) -> list[tuple[str, float, float]]:
    # (song_id, db_t_anchor, sample_t_anchor)
    hits: list[tuple[str, float, float]] = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        for h_sample, t_sample in sample_hashes:
            cur = conn.execute(
                "SELECT song_id, t_anchor FROM fingerprints WHERE hash = ?",
                (h_sample,),
            )
            for row in cur:
                hits.append((str(row["song_id"]), float(row["t_anchor"]), t_sample))
    return hits


def list_songs_from_db(db_path: Path) -> list[dict[str, int | str | float | None]]:
    songs: list[dict[str, int | str | float | None]] = []
    with sqlite3.connect(db_path) as conn:
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

    return songs


def count_songs_in_db(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute("SELECT COUNT(*) FROM songs")
        row = cur.fetchone()
        return int(row[0]) if row is not None else 0
