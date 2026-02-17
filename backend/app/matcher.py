from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from fingerprinter import AudioClip, Fingerprinter, fingerprint_hash
from storage import fetch_fingerprint_hits, get_song_name_by_id

# The score threshold for which to apply damping on confidence
LOW_CONFIDENCE_THRESHOLD = 7

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

        # Low confidence damping
        if best_count < LOW_CONFIDENCE_THRESHOLD:
            certainty *= best_count / LOW_CONFIDENCE_THRESHOLD

        certainty = int(round(certainty))

    return (best_song, timestamp_seconds, certainty)


def _build_song_bins_from_hits(
    hits: list[tuple[str, float, float]],
    time_bin_size: float,
) -> dict[str, dict[int, int]]:
    # song_id -> time_bin -> count
    song_bins: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for song_id, t_anchor_db, t_anchor_sample in hits:
        delta = t_anchor_db - t_anchor_sample
        time_bin = int(delta / time_bin_size)
        song_bins[song_id][time_bin] += 1
    return song_bins


def find_best_match(
    audio: AudioClip,
    db_path: Path,
    fingerprinter: Fingerprinter | None = None,
    time_bin_size: float = 0.5,
) -> tuple[str | None, float, float]:
    fp = fingerprinter or Fingerprinter()
    fingerprints, trim_offset_seconds = fp.fingerprints_from_audio(audio)

    config = fp.config
    hop_len = config.nperseg - config.noverlap

    # Build a lookup of sample hashes with their anchor times
    sample_hashes: list[tuple[int, float]] = []
    for item in fingerprints:
        h = fingerprint_hash(item)
        t_anchor = trim_offset_seconds + (item.t1 * hop_len / config.target_rate)
        sample_hashes.append((h, t_anchor))

    if not db_path.exists():
        return (None, 0.0, 0.0)

    hits = fetch_fingerprint_hits(
        db_path=db_path,
        sample_hashes=sample_hashes,
    )
    song_bins = _build_song_bins_from_hits(hits=hits, time_bin_size=time_bin_size)

    best_song, timestamp_seconds, certainty = select_match_from_song_bins(
        song_bins=song_bins,
        time_bin_size=time_bin_size,
    )

    if best_song is None:
        return (None, 0.0, 0.0)

    song_name = get_song_name_by_id(song_id=int(best_song), db_path=db_path)
    if song_name is None:
        return (best_song, timestamp_seconds, certainty)

    return (song_name, timestamp_seconds, certainty)
