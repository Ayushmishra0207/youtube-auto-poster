"""
Tracks recently-covered Shorts topics so repeated "Generate Short" clicks
(or back-to-back daily-pipeline Shorts) don't keep producing the same
story. Google News' top headline for a category barely changes within a
few hours, so without this, the LLM keeps picking the same dominant
headline (e.g. "HDFC Bank profit surge") as the lead story every time.

Two layers of defense, both driven by this module:
  1. Headline-level filtering — drop fetched headlines that closely match
     something already covered recently, before they ever reach the LLM.
  2. Prompt-level steering — pass recently-used titles into the prompt as
     an explicit "don't repeat these" list, for the LLM's own judgment
     within whatever headlines remain.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import BASE_DIR

HISTORY_TTL_HOURS = 72
MAX_HISTORY_ENTRIES = 200
_DUPLICATE_OVERLAP_THRESHOLD = 0.5

# Small, script-agnostic stopword set — just enough to stop trivial/generic
# news-boilerplate words (which appear in almost every headline regardless
# of story) from causing false-positive OR false-negative matches.
_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "for", "and", "to", "is", "are", "news", "today", "breaking",
    "after", "before", "over", "with", "from", "this", "that", "shorts",
    "से", "के", "की", "का", "में", "पर", "को", "है", "हैं", "और", "भी", "ने", "हो",
    "आज", "खबर", "खबरें", "बड़ी", "बड़ा", "समाचार", "अपडेट", "देखें",
}


def _fingerprint(text: str) -> tuple:
    """
    Returns (entity_tokens, general_tokens) for a headline/title.
    entity_tokens = Latin-script tokens (brand/person/place names are usually
    kept in Latin script or as a consistent transliteration — "HDFC" appears
    the same way across every headline about that story, even when the rest
    of the sentence is in Hindi and doesn't share a single common word with
    a differently-worded headline about the same thing).
    general_tokens = every distinctive word, any script — the overlap fallback.
    """
    words = re.findall(r"[\wऀ-ॿ]+", (text or "").lower())
    general = {w for w in words if len(w) > 2 and w not in _STOPWORDS}
    entities = {w for w in general if re.fullmatch(r"[a-z0-9]+", w)}
    return entities, general


def _history_path(namespace: str) -> Path:
    return BASE_DIR / f"{namespace}_topic_history.json"


def _load(namespace: str = "shorts") -> list:
    path = _history_path(namespace)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=HISTORY_TTL_HOURS)
    fresh = []
    for e in data:
        try:
            if datetime.fromisoformat(e["used_at"]) >= cutoff:
                fresh.append(e)
        except Exception:
            continue
    return fresh


def _save(entries: list, namespace: str = "shorts") -> None:
    _history_path(namespace).write_text(
        json.dumps(entries[-MAX_HISTORY_ENTRIES:], ensure_ascii=False, indent=2), encoding="utf-8"
    )


def record_topic(title: str, namespace: str = "shorts") -> None:
    """
    Call after a script is successfully generated, so future generations avoid
    repeating it. namespace picks which history file to use — "shorts"
    (default, unchanged) or "longform", so the two formats don't share a
    dedup pool unless you want them to.
    """
    if not title:
        return
    entities, general = _fingerprint(title)
    entries = _load(namespace)
    entries.append({
        "title": title,
        "entities": sorted(entities),
        "fingerprint": sorted(general),
        "used_at": datetime.now(timezone.utc).isoformat(),
    })
    _save(entries, namespace)


def recent_titles(limit: int = 15, namespace: str = "shorts") -> list:
    """Most recently used titles, for steering the LLM away from repeats."""
    return [e["title"] for e in _load(namespace)[-limit:]]


def is_duplicate(headline: str, threshold: float = _DUPLICATE_OVERLAP_THRESHOLD,
                 namespace: str = "shorts") -> bool:
    """
    True if headline matches a recent topic: either they share a distinctive
    Latin-script entity token (a brand/person/place name, e.g. "hdfc" —
    usually rendered identically across differently-worded headlines about
    the same story even when nothing else in the sentence matches), or their
    general word-overlap ratio exceeds threshold.
    """
    entities, fp = _fingerprint(headline)
    if not entities and not fp:
        return False
    for e in _load(namespace):
        used_entities = set(e.get("entities", []))
        if entities and used_entities and (entities & used_entities):
            return True
        used_fp = set(e.get("fingerprint", []))
        if not used_fp or not fp:
            continue
        overlap = len(fp & used_fp) / max(1, min(len(fp), len(used_fp)))
        if overlap >= threshold:
            return True
    return False


def filter_fresh(headlines: list, namespace: str = "shorts") -> list:
    """Drop headlines that duplicate something covered recently."""
    return [h for h in headlines if not is_duplicate(h, namespace=namespace)]
