import tempfile
from pathlib import Path

import moviepy as mpe
import numpy as np

from pipeline.video_creator import build_chapters


def _make_silent_mp3(path: str, seconds: float):
    def make_frame(t):
        if np.isscalar(t):
            return np.array([0.0, 0.0])
        return np.zeros((len(t), 2))
    clip = mpe.AudioClip(make_frame, duration=seconds, fps=44100)
    clip.write_audiofile(path, logger=None)
    clip.close()


def test_build_chapters_matches_pure_offsets():
    with tempfile.TemporaryDirectory() as tmp:
        v1 = str(Path(tmp) / "v1.mp3")
        v2 = str(Path(tmp) / "v2.mp3")
        _make_silent_mp3(v1, 20.0)
        _make_silent_mp3(v2, 15.0)
        script = {"sections": [{"heading": "पहला हिस्सा"}, {"heading": "दूसरा हिस्सा"}]}
        result = build_chapters(script, [v1, v2])
        lines = result.strip().split("\n")
        assert len(lines) == 2
        assert lines[0] == "0:00 पहला हिस्सा"
        assert "दूसरा हिस्सा" in lines[1]


def test_build_chapters_skips_missing_voice():
    with tempfile.TemporaryDirectory() as tmp:
        v1 = str(Path(tmp) / "v1.mp3")
        _make_silent_mp3(v1, 20.0)
        script = {"sections": [{"heading": "पहला हिस्सा"}, {"heading": "गायब हिस्सा"}]}
        result = build_chapters(script, [v1, ""])
        assert "गायब हिस्सा" not in result


def test_build_chapters_merges_short_gap():
    with tempfile.TemporaryDirectory() as tmp:
        v1 = str(Path(tmp) / "v1.mp3")
        v2 = str(Path(tmp) / "v2.mp3")
        v3 = str(Path(tmp) / "v3.mp3")
        _make_silent_mp3(v1, 20.0)
        _make_silent_mp3(v2, 3.0)
        _make_silent_mp3(v3, 20.0)
        script = {"sections": [
            {"heading": "भाग 1"}, {"heading": "भाग 2"}, {"heading": "भाग 3"},
        ]}
        result = build_chapters(script, [v1, v2, v3])
        assert "भाग 3" not in result
        assert "भाग 2" in result


if __name__ == "__main__":
    test_build_chapters_matches_pure_offsets()
    test_build_chapters_skips_missing_voice()
    test_build_chapters_merges_short_gap()
    print("All tests passed.")
