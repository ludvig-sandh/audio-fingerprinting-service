from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from insert_song import Fingerprinter, fingerprint_hash
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

    with db_path.open("r", encoding="utf-8") as f:
        for line in tqdm(f, desc="Matching fingerprints"):
            parts = line.strip().split("\t")
            if len(parts) != 3:
                continue
            h_str, song_id, t_str = parts
            try:
                h_db = int(h_str)
                t_db = float(t_str)
            except ValueError:
                continue

            # Compare against all sample hashes with matching hash
            for h_sample, t_sample in sample_hashes:
                if h_sample != h_db:
                    continue
                delta = t_db - t_sample
                time_bin = int(delta / time_bin_size)
                song_bins[song_id][time_bin] += 1

    best_song = None
    best_count = 0
    best_time_bin = 0
    second_best = 0

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
        return (None, 0.0, 0.0)

    timestamp_seconds = best_time_bin * time_bin_size
    certainty = best_count / second_best if second_best > 0 else float("inf")
    return (best_song, timestamp_seconds, certainty)


def main() -> None:
    db_path = Path("fingerprints.txt")
    fingerprinter = Fingerprinter()

    wav_paths = [
        # Insert song paths here
    ]

    for wav_path in wav_paths:
        if not wav_path.exists():
            raise FileNotFoundError(
                f"Missing WAV file at {wav_path.resolve()} - update wav_path."
            )
        song_id, timestamp, certainty = find_best_match(
            wav_path, db_path, fingerprinter=fingerprinter
        )
        if song_id is None:
            print(f"No match found for {wav_path.stem}.")
        else:
            print(
                f"Best match for {wav_path.stem}: {song_id} @ {timestamp:.2f}s "
                f"(certainty {certainty:.2f})"
            )


if __name__ == "__main__":
    main()
