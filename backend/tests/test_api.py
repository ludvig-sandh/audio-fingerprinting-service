from __future__ import annotations

import importlib
import sys
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def load_api_module(tmp_path: Path, max_upload_bytes: int = 50 * 1024 * 1024):
    import os

    os.environ["FP_DB_PATH"] = str(tmp_path / "test.db")
    os.environ["ADMIN_API_KEY"] = "test-secret"
    os.environ["MAX_UPLOAD_BYTES"] = str(max_upload_bytes)
    os.environ.pop("MAX_SONGS", None)

    if "api" in sys.modules:
        return importlib.reload(sys.modules["api"])
    return importlib.import_module("api")


def test_list_songs_empty(tmp_path):
    api = load_api_module(tmp_path)
    client = TestClient(api.app)

    res = client.get("/songs")

    assert res.status_code == 200
    assert res.json() == {"songs": []}


def test_insert_song_requires_api_key(tmp_path):
    api = load_api_module(tmp_path)
    client = TestClient(api.app)

    res = client.post(
        "/songs",
        files={"file": ("song.wav", b"fake-wav", "audio/wav")},
    )

    assert res.status_code == 401


def test_insert_song_rejects_short_audio(tmp_path, monkeypatch):
    api = load_api_module(tmp_path)
    client = TestClient(api.app)

    monkeypatch.setattr(
        api,
        "load_wav_mono_bytes",
        lambda _bytes: (11025, np.zeros(59 * 11025, dtype=np.float32)),
    )
    monkeypatch.setattr(api, "insert_song", lambda **_kwargs: 1)

    res = client.post(
        "/songs",
        headers={"X-API-Key": "test-secret"},
        files={"file": ("song.wav", b"fake-wav", "audio/wav")},
    )

    assert res.status_code == 400
    assert "too short" in res.json()["detail"].lower()


def test_insert_song_rejects_long_audio(tmp_path, monkeypatch):
    api = load_api_module(tmp_path)
    client = TestClient(api.app)

    monkeypatch.setattr(
        api,
        "load_wav_mono_bytes",
        lambda _bytes: (11025, np.zeros(301 * 11025, dtype=np.float32)),
    )
    monkeypatch.setattr(api, "insert_song", lambda **_kwargs: 1)

    res = client.post(
        "/songs",
        headers={"X-API-Key": "test-secret"},
        files={"file": ("song.wav", b"fake-wav", "audio/wav")},
    )

    assert res.status_code == 400
    assert "too long" in res.json()["detail"].lower()


def test_insert_song_accepts_valid_length_audio(tmp_path, monkeypatch):
    api = load_api_module(tmp_path)
    client = TestClient(api.app)

    monkeypatch.setattr(
        api,
        "load_wav_mono_bytes",
        lambda _bytes: (11025, np.zeros(300 * 11025, dtype=np.float32)),
    )
    monkeypatch.setattr(api, "insert_song", lambda **_kwargs: 1)

    res = client.post(
        "/songs",
        headers={"X-API-Key": "test-secret"},
        files={"file": ("song.wav", b"fake-wav", "audio/wav")},
    )

    assert res.status_code == 200
    payload = res.json()
    assert payload["song_id"] == 1
    assert payload["song_name"] == "song"


def test_insert_song_rejects_unsupported_sample_rate(tmp_path, monkeypatch):
    api = load_api_module(tmp_path)
    client = TestClient(api.app)

    monkeypatch.setattr(
        api,
        "load_wav_mono_bytes",
        lambda _bytes: (12345, np.zeros(120 * 12345, dtype=np.float32)),
    )

    res = client.post(
        "/songs",
        headers={"X-API-Key": "test-secret"},
        files={"file": ("song.wav", b"fake-wav", "audio/wav")},
    )

    assert res.status_code == 400
    assert "unsupported sample rate" in res.json()["detail"].lower()


def test_insert_song_accepts_supported_sample_rate(tmp_path, monkeypatch):
    api = load_api_module(tmp_path)
    client = TestClient(api.app)

    monkeypatch.setattr(
        api,
        "load_wav_mono_bytes",
        lambda _bytes: (44100, np.zeros(120 * 44100, dtype=np.float32)),
    )
    monkeypatch.setattr(api, "insert_song", lambda **_kwargs: 1)

    res = client.post(
        "/songs",
        headers={"X-API-Key": "test-secret"},
        files={"file": ("song.wav", b"fake-wav", "audio/wav")},
    )

    assert res.status_code == 200
    assert res.json()["song_id"] == 1


def test_identify_timestamp_is_integer(tmp_path, monkeypatch):
    api = load_api_module(tmp_path)
    client = TestClient(api.app)

    monkeypatch.setattr(
        api,
        "load_wav_mono_bytes",
        lambda _bytes: (11025, np.zeros(2 * 11025, dtype=np.float32)),
    )
    monkeypatch.setattr(
        api,
        "find_best_match",
        lambda **_kwargs: ("abba", 10.4, 82),
    )

    res = client.post(
        "/identify",
        files={"file": ("sample.wav", b"fake-wav", "audio/wav")},
    )

    assert res.status_code == 200
    payload = res.json()
    assert payload["match"]["song_name"] == "abba"
    assert isinstance(payload["match"]["timestamp_seconds"], int)
    assert payload["match"]["timestamp_seconds"] == 12


def test_identify_rejects_unsupported_sample_rate(tmp_path, monkeypatch):
    api = load_api_module(tmp_path)
    client = TestClient(api.app)

    monkeypatch.setattr(
        api,
        "load_wav_mono_bytes",
        lambda _bytes: (12345, np.zeros(2 * 12345, dtype=np.float32)),
    )

    res = client.post(
        "/identify",
        files={"file": ("sample.wav", b"fake-wav", "audio/wav")},
    )

    assert res.status_code == 400
    assert "unsupported sample rate" in res.json()["detail"].lower()


def test_identify_respects_upload_size_limit(tmp_path):
    api = load_api_module(tmp_path, max_upload_bytes=8)
    client = TestClient(api.app)

    res = client.post(
        "/identify",
        files={"file": ("sample.wav", b"0123456789", "audio/wav")},
    )

    assert res.status_code == 413
    assert "file too large" in res.json()["detail"].lower()


def test_insert_song_respects_max_songs_limit(tmp_path, monkeypatch):
    import sqlite3

    api = load_api_module(tmp_path)
    api.MAX_SONGS = 1
    client = TestClient(api.app)

    monkeypatch.setattr(
        api,
        "_load_upload_audio",
        lambda _file: api.AudioClip(sample_rate=11025, mono=np.zeros(11025, dtype=np.float32)),
    )

    with sqlite3.connect(api.DB_PATH) as conn:
        conn.execute(
            "INSERT INTO songs (name, length_seconds) VALUES (?, ?)",
            ("seed-song", 180.0),
        )

    res = client.post(
        "/songs",
        headers={"X-API-Key": "test-secret"},
        files={"file": ("new.wav", b"fake-wav", "audio/wav")},
    )
    assert res.status_code == 400
    assert "song limit reached" in res.json()["detail"].lower()


def test_identify_rejects_sample_longer_than_15_seconds(tmp_path, monkeypatch):
    api = load_api_module(tmp_path)
    client = TestClient(api.app)

    monkeypatch.setattr(
        api,
        "load_wav_mono_bytes",
        lambda _bytes: (11025, np.zeros(16 * 11025, dtype=np.float32)),
    )
    monkeypatch.setattr(
        api,
        "find_best_match",
        lambda **_kwargs: ("abba", 5.0, 70),
    )

    res = client.post(
        "/identify",
        files={"file": ("sample.wav", b"fake-wav", "audio/wav")},
    )

    assert res.status_code == 400
    assert "sample is too long" in res.json()["detail"].lower()


def test_delete_song_requires_api_key(tmp_path, monkeypatch):
    api = load_api_module(tmp_path)
    client = TestClient(api.app)

    monkeypatch.setattr(
        api,
        "load_wav_mono_bytes",
        lambda _bytes: (11025, np.zeros(120 * 11025, dtype=np.float32)),
    )
    monkeypatch.setattr(api, "insert_song", lambda **_kwargs: 1)

    create = client.post(
        "/songs",
        headers={"X-API-Key": "test-secret"},
        files={"file": ("song.wav", b"fake-wav", "audio/wav")},
    )
    assert create.status_code == 200

    res = client.delete("/songs/1")
    assert res.status_code == 401


def test_delete_song_not_found(tmp_path):
    api = load_api_module(tmp_path)
    client = TestClient(api.app)

    res = client.delete(
        "/songs/9999",
        headers={"X-API-Key": "test-secret"},
    )
    assert res.status_code == 404
    assert "song not found" in res.json()["detail"].lower()


def test_insert_song_fails_for_duplicate_song_name(tmp_path, monkeypatch):
    api = load_api_module(tmp_path)
    client = TestClient(api.app)

    monkeypatch.setattr(
        api,
        "_load_upload_audio",
        lambda _file: api.AudioClip(sample_rate=11025, mono=np.zeros(120 * 11025, dtype=np.float32)),
    )
    monkeypatch.setattr(
        api.FINGERPRINTER,
        "fingerprints_from_audio",
        lambda _audio: ([], 0.0),
    )

    first = client.post(
        "/songs",
        headers={"X-API-Key": "test-secret"},
        params={"song_name": "existing-song"},
        files={"file": ("song.wav", b"fake-wav", "audio/wav")},
    )
    assert first.status_code == 200

    duplicate = client.post(
        "/songs",
        headers={"X-API-Key": "test-secret"},
        params={"song_name": "existing-song"},
        files={"file": ("song.wav", b"fake-wav", "audio/wav")},
    )
    assert duplicate.status_code == 409
    assert "already exists" in duplicate.json()["detail"].lower()
