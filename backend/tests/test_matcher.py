from __future__ import annotations

import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from matcher import select_match_from_song_bins


def test_select_match_from_song_bins_returns_none_for_empty():
    best_song, timestamp_seconds, certainty = select_match_from_song_bins(
        song_bins={},
        time_bin_size=0.5,
    )

    assert best_song is None
    assert timestamp_seconds == 0.0
    assert certainty == 0


def test_select_match_from_song_bins_picks_highest_vote_song_and_time_bin():
    song_bins = {
        "songA": {2: 3, 4: 6},
        "songB": {1: 4, 8: 5},
    }

    best_song, timestamp_seconds, certainty = select_match_from_song_bins(
        song_bins=song_bins,
        time_bin_size=0.5,
    )

    assert best_song == "songA"
    assert timestamp_seconds == 2.0
    assert certainty == 74


def test_select_match_from_song_bins_applies_low_match_damping():
    song_bins = {
        "songA": {6: 3},
        "songB": {2: 1},
    }

    best_song, timestamp_seconds, certainty = select_match_from_song_bins(
        song_bins=song_bins,
        time_bin_size=0.5,
    )

    assert best_song == "songA"
    assert timestamp_seconds == 3.0
    assert certainty == 52
