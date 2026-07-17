import tempfile
from pathlib import Path

import moviepy as mpe
import numpy as np

from scheduler import _append_chapters_to_description


def _make_silent_mp3(path: str, seconds: float):
    def make_frame(t):
        if np.isscalar(t):
            return np.array([0.0, 0.0])
        return np.zeros((len(t), 2))
    clip = mpe.AudioClip(make_frame, duration=seconds, fps=44100)
    clip.write_audiofile(path, logger=None)
    clip.close()


def test_appends_chapters_to_existing_description():
    with tempfile.TemporaryDirectory() as tmp:
        v1 = str(Path(tmp) / "v1.mp3")
        _make_silent_mp3(v1, 20.0)
        script = {
            "description": "यह एक हुक लाइन है। #Hindi #News",
            "sections": [{"heading": "पहला हिस्सा"}],
        }
        result = _append_chapters_to_description(script, [v1])
        assert "यह एक हुक लाइन है" in result["description"]
        assert "0:00 पहला हिस्सा" in result["description"]


if __name__ == "__main__":
    test_appends_chapters_to_existing_description()
    print("All tests passed.")
