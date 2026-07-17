from pipeline.script_generator import _SYSTEM_PROMPT


def test_title_keyword_placement_rule_present():
    assert "first 40 characters" in _SYSTEM_PROMPT or "first 40 chars" in _SYSTEM_PROMPT


def test_description_structure_rules_present():
    assert "hook line" in _SYSTEM_PROMPT.lower()
    assert "hashtag" in _SYSTEM_PROMPT.lower()


def test_tag_count_and_ordering_rule_present():
    assert "20-25" in _SYSTEM_PROMPT
    assert "broad" in _SYSTEM_PROMPT.lower()


def test_schema_keys_unchanged():
    for key in ("title", "title_english", "description", "tags", "thumbnail_text", "sections"):
        assert f'"{key}"' in _SYSTEM_PROMPT


if __name__ == "__main__":
    test_title_keyword_placement_rule_present()
    test_description_structure_rules_present()
    test_tag_count_and_ordering_rule_present()
    test_schema_keys_unchanged()
    print("All tests passed.")
