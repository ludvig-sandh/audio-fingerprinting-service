from __future__ import annotations

from pathlib import Path

from fingerprinter import Fingerprinter, fingerprint_hash


def append_fingerprints_to_db(
    wav_path: Path,
    db_path: Path,
    fingerprinter: Fingerprinter | None = None,
    song_id: str | None = None,
) -> int:
    fp = fingerprinter or Fingerprinter()
    fingerprints, trim_offset_seconds = fp.fingerprints_from_wav(wav_path)

    config = fp.config
    hop_len = config.nperseg - config.noverlap
    if hop_len <= 0:
        raise ValueError("Invalid hop length; noverlap must be < nperseg.")

    song_key = song_id or wav_path.stem
    with db_path.open("a", encoding="utf-8") as f:
        for item in fingerprints:
            h = fingerprint_hash(item)
            t_anchor = trim_offset_seconds + (item.t1 * hop_len / config.target_rate)
            f.write(f"{h}\t{song_key}\t{t_anchor:.6f}\n")
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
