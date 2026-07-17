# tests/test_generate_script_wiring.py
from unittest.mock import patch
from pipeline import script_generator


def test_generate_script_applies_enrichment():
    fake_script = {"title": "t", "description": "hook", "tags": [], "sections": []}
    with patch.object(script_generator, "_generate_via_chain", return_value=fake_script):
        result = script_generator.generate_script("some topic")
    assert "bitnomad1" in [t.lower() for t in result["tags"]]
    assert "#" in result["description"]


def test_generate_shorts_script_applies_enrichment():
    fake_script = {"title": "t", "description": "hook", "tags": [], "items": []}
    with patch.object(script_generator, "_generate_via_chain", return_value=fake_script):
        result = script_generator.generate_shorts_script(["headline 1", "headline 2", "headline 3"])
    assert "shorts" in [t.lower() for t in result["tags"]]
    assert "#" in result["description"]


if __name__ == "__main__":
    test_generate_script_applies_enrichment()
    test_generate_shorts_script_applies_enrichment()
    print("All tests passed.")
