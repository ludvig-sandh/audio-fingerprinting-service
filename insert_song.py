from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly, spectrogram
from scipy.ndimage import maximum_filter


def load_wav_mono(path: Path) -> tuple[int, np.ndarray]:
    sample_rate, data = wavfile.read(path)
    if data.ndim == 1:
        mono = data.astype(np.float32)
    else:
        # Average channels to mono
        mono = data.astype(np.float32).mean(axis=1)
    # Normalize to [-1, 1] if integer PCM
    if np.issubdtype(data.dtype, np.integer):
        max_val = np.iinfo(data.dtype).max
        if max_val > 0:
            mono = mono / max_val
    return sample_rate, mono


def trim_silence(
    signal: np.ndarray,
    sample_rate: int,
    threshold_db: float = -40.0,
    frame_ms: float = 20.0,
    min_silence_ms: float = 200.0,
) -> tuple[np.ndarray, int]:
    frame_len = max(1, int(sample_rate * frame_ms / 1000.0))
    hop_len = frame_len
    if signal.size < frame_len:
        return signal, 0

    frames = signal[: (signal.size // hop_len) * hop_len].reshape(-1, hop_len)
    rms = np.sqrt(np.mean(frames**2, axis=1)) + 1e-12
    rms_db = 20.0 * np.log10(rms)

    mask = rms_db > threshold_db
    if not np.any(mask):
        return signal, 0

    min_frames = max(1, int(min_silence_ms / frame_ms))
    # Smooth mask by requiring runs of non-silence
    idx = np.where(mask)[0]
    start = idx[0]
    end = idx[-1]
    # Expand start/end to include contiguous runs longer than min_frames
    # Find first run of True with length >= min_frames
    run_start = None
    run_len = 0
    for i, v in enumerate(mask):
        if v:
            if run_start is None:
                run_start = i
                run_len = 1
            else:
                run_len += 1
            if run_len >= min_frames:
                start = run_start
                break
        else:
            run_start = None
            run_len = 0
    # Find last run of True with length >= min_frames
    run_start = None
    run_len = 0
    for i in range(mask.size - 1, -1, -1):
        if mask[i]:
            if run_start is None:
                run_start = i
                run_len = 1
            else:
                run_len += 1
            if run_len >= min_frames:
                end = run_start
                break
        else:
            run_start = None
            run_len = 0

    start_sample = start * hop_len
    end_sample = min(signal.size, (end + 1) * hop_len)
    return signal[start_sample:end_sample], start_sample


def compute_spectrogram(
    sample_rate: int,
    signal: np.ndarray,
    nperseg: int = 2048,
    noverlap: int = 1536,
) -> np.ndarray:
    _, _, sxx = spectrogram(
        signal,
        fs=sample_rate,
        nperseg=nperseg,
        noverlap=noverlap,
        scaling="spectrum",
    )
    sxx_db = 10 * np.log10(sxx + 1e-10)
    return sxx_db


def extract_peaks(
    sxx_db: np.ndarray,
    neighborhood_size: int = 20,
) -> np.ndarray:
    neighborhood = maximum_filter(sxx_db, size=neighborhood_size, mode="constant")
    local_max = sxx_db == neighborhood
    return np.argwhere(local_max)


def generate_fingerprints(
    peaks: np.ndarray,
    fanout: int = 7,
    max_time_delta: int = 50,
    max_freq_delta: int = 30,
) -> list["Fingerprint"]:
    if peaks.size == 0:
        return []

    # peaks are (freq_bin, time_bin)
    order = np.argsort(peaks[:, 1])
    peaks_sorted = peaks[order]

    fingerprints: list[Fingerprint] = []
    n = peaks_sorted.shape[0]
    for i in range(n):
        f1, t1 = peaks_sorted[i]
        matches = 0
        for j in range(i + 1, n):
            f2, t2 = peaks_sorted[j]
            dt = t2 - t1
            if dt > max_time_delta:
                break
            if abs(f2 - f1) > max_freq_delta:
                continue
            fingerprints.append(Fingerprint(f1=f1, t1=t1, f2=f2, t2=t2, dt=dt))
            matches += 1
            if matches >= fanout:
                break
    return fingerprints


@dataclass(frozen=True)
class Fingerprint:
    f1: int
    t1: int
    f2: int
    t2: int
    dt: int


@dataclass(frozen=True)
class FingerprinterConfig:
    target_rate: int = 11_025
    nperseg: int = 2048
    noverlap: int = 1536
    neighborhood_size: int = 20
    fanout: int = 7
    max_time_delta: int = 50
    max_freq_delta: int = 30


class Fingerprinter:
    def __init__(self, config: FingerprinterConfig | None = None) -> None:
        self.config = config or FingerprinterConfig()

    def fingerprints_from_wav(self, wav_path: Path) -> tuple[list[Fingerprint], float]:
        sample_rate, mono = load_wav_mono(wav_path)
        mono, trim_start = trim_silence(mono, sample_rate)
        trim_offset_seconds = trim_start / sample_rate

        if sample_rate != self.config.target_rate:
            from math import gcd

            g = gcd(sample_rate, self.config.target_rate)
            up = self.config.target_rate // g
            down = sample_rate // g
            mono = resample_poly(mono, up, down)
            sample_rate = self.config.target_rate

        sxx_db = compute_spectrogram(
            sample_rate,
            mono,
            nperseg=self.config.nperseg,
            noverlap=self.config.noverlap,
        )
        peaks = extract_peaks(sxx_db, neighborhood_size=self.config.neighborhood_size)
        fingerprints = generate_fingerprints(
            peaks,
            fanout=self.config.fanout,
            max_time_delta=self.config.max_time_delta,
            max_freq_delta=self.config.max_freq_delta,
        )
        return fingerprints, trim_offset_seconds


def fingerprint_hash(
    fp: Fingerprint,
    freq_max: int = 8191,  # 13 bits
    dt_max: int = 63,  # 6 bits
) -> int:
    f1 = min(max(fp.f1, 0), freq_max)
    f2 = min(max(fp.f2, 0), freq_max)
    dt = min(max(fp.dt, 0), dt_max)
    return (f1 << 19) | (f2 << 6) | dt


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


def main() -> None:
    # Hardcode a local path to a .wav file
    db_path = Path("fingerprints.txt")
    fingerprinter = Fingerprinter()

    wav_paths = [
        # Insert song paths here
    ]

    total = 0
    for wav_path in wav_paths:
        count = insert_song(wav_path, db_path, fingerprinter=fingerprinter)
        total += count
        print(f"Appended {count} fingerprints for {wav_path.stem}")
    print(f"Total appended: {total} -> {db_path.resolve()}")

if __name__ == "__main__":
    main()
