from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import sqlite3

from fingerprinter import Fingerprinter, fingerprint_hash


def select_match_from_song_bins(
    song_bins: dict[str, dict[int, int]],
    time_bin_size: float,
) -> tuple[str | None, float, int]:
    best_song = None
    best_count = 0
    second_best = 0
    best_time_bin = 0

    for song_id, bins in song_bins.items():
        if not bins:
            continue
        top_bin, top_count = max(bins.items(), key=lambda x: x[1])
        if top_count > best_count:
            second_best = best_count
            best_count = top_count
            best_song = song_id
            best_time_bin = top_bin
        elif top_count > second_best:
            second_best = top_count

    if best_song is None:
        return (None, 0.0, 0)

    timestamp_seconds = best_time_bin * time_bin_size
    denom = best_count + second_best
    if denom == 0:
        certainty = 0
    else:
        certainty = (best_count / denom) ** 0.5 * 100.0
        if best_count < 5:
            certainty *= best_count / 5
        certainty = int(round(certainty))

    return (best_song, timestamp_seconds, certainty)


def _resolve_song_name(db_path: Path, song_id: str) -> str:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT name FROM songs WHERE id = ?", (int(song_id),))
        row = cur.fetchone()
        if row is None:
            return song_id
        return str(row["name"])


def _build_song_bins(
    db_path: Path,
    sample_hashes: list[tuple[int, float]],
    time_bin_size: float,
) -> dict[str, dict[int, int]]:
    # song_id -> time_bin -> count
    song_bins: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        for h_sample, t_sample in sample_hashes:
            cur = conn.execute(
                "SELECT song_id, t_anchor FROM fingerprints WHERE hash = ?",
                (h_sample,),
            )
            for row in cur:
                delta = row["t_anchor"] - t_sample
                time_bin = int(delta / time_bin_size)
                song_bins[str(row["song_id"])][time_bin] += 1
    return song_bins


def find_best_match(
    wav_path: Path,
    db_path: Path,
    fingerprinter: Fingerprinter | None = None,
    time_bin_size: float = 0.5,
) -> tuple[str | None, float, float]:
    fp = fingerprinter or Fingerprinter()
    fingerprints, trim_offset_seconds = fp.fingerprints_from_wav(wav_path)

    config = fp.config
    hop_len = config.nperseg - config.noverlap
    if hop_len <= 0:
        raise ValueError("Invalid hop length; noverlap must be < nperseg.")

    # Build a lookup of sample hashes with their anchor times
    sample_hashes: list[tuple[int, float]] = []
    for item in fingerprints:
        h = fingerprint_hash(item)
        t_anchor = trim_offset_seconds + (item.t1 * hop_len / config.target_rate)
        sample_hashes.append((h, t_anchor))

    if not db_path.exists():
        return (None, 0.0, 0.0)

    song_bins = _build_song_bins(
        db_path=db_path,
        sample_hashes=sample_hashes,
        time_bin_size=time_bin_size,
    )

    best_song, timestamp_seconds, certainty = select_match_from_song_bins(
        song_bins=song_bins,
        time_bin_size=time_bin_size,
    )

    if best_song is None:
        return (None, 0.0, 0.0)

    song_name = _resolve_song_name(db_path=db_path, song_id=best_song)

    return (song_name, timestamp_seconds, certainty)
