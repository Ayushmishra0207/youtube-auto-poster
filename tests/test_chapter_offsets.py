from pipeline.video_creator import _compute_chapter_offsets, _format_timestamp


def test_format_timestamp_basic():
    assert _format_timestamp(0) == "0:00"
    assert _format_timestamp(65) == "1:05"
    assert _format_timestamp(599.6) == "10:00"


def test_first_chapter_forced_to_zero():
    offsets = _compute_chapter_offsets(
        section_headings=["भाग 1", "भाग 2"],
        section_durations=[20.0, 15.0],
    )
    assert offsets[0][0] == 0.0
    assert offsets[0][1] == "भाग 1"


def test_skips_section_with_no_duration():
    offsets = _compute_chapter_offsets(
        section_headings=["भाग 1", "गायब"],
        section_durations=[20.0, None],
    )
    assert len(offsets) == 1
    assert offsets[0][1] == "भाग 1"


def test_merges_chapter_closer_than_minimum_gap():
    offsets = _compute_chapter_offsets(
        section_headings=["भाग 1", "भाग 2", "भाग 3"],
        section_durations=[20.0, 3.0, 20.0],
    )
    headings = [h for _, h in offsets]
    assert "भाग 3" not in headings
    assert "भाग 2" in headings


if __name__ == "__main__":
    test_format_timestamp_basic()
    test_first_chapter_forced_to_zero()
    test_skips_section_with_no_duration()
    test_merges_chapter_closer_than_minimum_gap()
    print("All tests passed.")
