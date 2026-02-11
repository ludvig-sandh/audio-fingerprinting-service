from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import sqlite3

from fingerprinter import Fingerprinter, fingerprint_hash
from tqdm import tqdm


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

    # song_id -> time_bin -> count
    song_bins: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))

    # Build a lookup of sample hashes with their anchor times
    sample_hashes: list[tuple[int, float]] = []
    for item in fingerprints:
        h = fingerprint_hash(item)
        t_anchor = trim_offset_seconds + (item.t1 * hop_len / config.target_rate)
        sample_hashes.append((h, t_anchor))

    if not db_path.exists():
        return (None, 0.0, 0.0)

    matched_sample_fingerprints = 0
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        for h_sample, t_sample in tqdm(sample_hashes, desc="Matching fingerprints"):
            cur = conn.execute(
                "SELECT song_id, t_anchor FROM fingerprints WHERE hash = ?",
                (h_sample,),
            )
            found_for_this_fingerprint = False
            for row in cur:
                found_for_this_fingerprint = True
                delta = row["t_anchor"] - t_sample
                time_bin = int(delta / time_bin_size)
                song_bins[str(row["song_id"])][time_bin] += 1
            if found_for_this_fingerprint:
                matched_sample_fingerprints += 1

    best_song = None
    best_count = 0
    best_time_bin = 0

    song_name_lookup: dict[str, str] = {}
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT id, name FROM songs")
        for row in cur:
            song_name_lookup[str(row["id"])] = row["name"]

    per_song_scores: dict[str, tuple[int, int]] = {}
    for song_id, bins in song_bins.items():
        if not bins:
            continue
        top_bin, top_count = max(bins.items(), key=lambda x: x[1])
        per_song_scores[song_id] = (top_bin, top_count)
        if top_count > best_count:
            best_count = top_count
            best_song = song_id
            best_time_bin = top_bin

    if best_song is None:
        return (None, 0.0, 0.0)
    
    timestamp_seconds = best_time_bin * time_bin_size
    total_count = sum(score for _, score in per_song_scores.values())
    if total_count == 0:
        certainty = 0
    else:
        certainty = (best_count / total_count) ** 0.5 * 100.0

        # In case of low matches, don't be overly confident
        if total_count < 5:
            certainty *= total_count / 5

        certainty = int(round(certainty))
    for song_id, (_, score) in sorted(
        per_song_scores.items(), key=lambda item: item[1][1], reverse=True
    ):
        song_name = song_name_lookup.get(song_id, song_id)
        print(f"[match] song={song_name} score={score}")
    print(
        f"[match] matched_sample_fingerprints={matched_sample_fingerprints}/{len(sample_hashes)}"
    )

    song_name = song_name_lookup.get(best_song, best_song)
    return (song_name, timestamp_seconds, certainty)
