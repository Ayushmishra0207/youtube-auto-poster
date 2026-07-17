from pipeline.script_generator import _enrich_metadata


def test_dedupes_case_insensitive_tags():
    script = {"tags": ["Hindi News", "HINDI news", "corruption"], "description": "hook"}
    result = _enrich_metadata(script, is_short=False)
    lowered = [t.lower() for t in result["tags"]]
    assert lowered.count("hindi news") == 1


def test_base_tags_always_present():
    script = {"tags": [], "description": "hook"}
    result = _enrich_metadata(script, is_short=False)
    assert "bitnomad1" in [t.lower() for t in result["tags"]]


def test_caps_tag_count():
    script = {"tags": [f"tag{i}" for i in range(50)], "description": "hook"}
    result = _enrich_metadata(script, is_short=False)
    assert len(result["tags"]) <= 25


def test_caps_total_char_length():
    script = {"tags": ["x" * 100 for _ in range(10)], "description": "hook"}
    result = _enrich_metadata(script, is_short=False)
    joined_len = sum(len(t) for t in result["tags"]) + max(0, len(result["tags"]) - 1)
    assert joined_len <= 500


def test_appends_default_hashtags_when_missing():
    script = {"tags": [], "description": "no hashtags here"}
    result = _enrich_metadata(script, is_short=False)
    assert "#" in result["description"]


def test_keeps_existing_hashtags_untouched():
    script = {"tags": [], "description": "hook #MyOwnTag"}
    result = _enrich_metadata(script, is_short=False)
    assert result["description"] == "hook #MyOwnTag"


def test_shorts_uses_shorts_base_tags():
    script = {"tags": [], "description": "hook"}
    result = _enrich_metadata(script, is_short=True)
    assert "shorts" in [t.lower() for t in result["tags"]]


if __name__ == "__main__":
    test_dedupes_case_insensitive_tags()
    test_base_tags_always_present()
    test_caps_tag_count()
    test_caps_total_char_length()
    test_appends_default_hashtags_when_missing()
    test_keeps_existing_hashtags_untouched()
    test_shorts_uses_shorts_base_tags()
    print("All tests passed.")
