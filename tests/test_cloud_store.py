"""
db / auth / state_store / media_store against both backends:
  • SQLite (always)
  • Postgres when TEST_DATABASE_URL is set (CI runs a postgres:16 service)
"""
import json
import os
import threading

import pytest

BACKENDS = ["sqlite"] + (["postgres"] if os.environ.get("TEST_DATABASE_URL") else [])


@pytest.fixture(params=BACKENDS)
def backend(request, tmp_path, monkeypatch):
    import db
    if request.param == "postgres":
        monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
        db.init_db()
        with db.db_cursor() as cur:   # clean slate between tests
            for t in ("sessions", "youtube_accounts", "users", "app_state", "media_items"):
                cur.execute(f"DELETE FROM {t}")
    else:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setattr(db, "DB_PATH", tmp_path / "app.db")
        db._initialized = False
        db.init_db()
    yield request.param
    db._initialized = False


def test_auth_roundtrip(backend):
    import auth
    import db
    uid = auth.create_user("alice", "s3cret!")
    assert isinstance(uid, int) and uid > 0
    assert auth.verify_user("alice", "s3cret!") == uid
    assert auth.verify_user("alice", "wrong") is None
    with pytest.raises(db.IntegrityError):
        auth.create_user("alice", "again")
    assert auth.ensure_user("alice", "newpass") == uid
    assert auth.verify_user("alice", "newpass") == uid
    token = auth.create_session(uid)
    assert auth.get_user_for_session(token) == {"id": uid, "username": "alice"}
    auth.delete_session(token)
    assert auth.get_user_for_session(token) is None


def test_state_store_cloud_and_mutate(backend, monkeypatch, tmp_path):
    from pipeline import state_store
    if backend == "sqlite":
        # local mode uses files under BASE_DIR — point it at a temp dir
        monkeypatch.setattr(state_store, "BASE_DIR", tmp_path)
    key = "unit_test_state.json"
    assert state_store.load(key, {"n": 0}) == {"n": 0}
    state_store.save(key, {"n": 1, "hi": "नमस्ते"})
    assert state_store.load(key) == {"n": 1, "hi": "नमस्ते"}

    def bump(st):
        st["n"] += 1
        return st["n"]

    threads = [threading.Thread(target=lambda: state_store.mutate(key, bump, {"n": 0})) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert state_store.load(key)["n"] == 9        # no lost updates
    state_store.delete(key)
    assert not state_store.exists(key)


def test_media_index(backend):
    from pipeline import media_store
    assert media_store.max_index("2026-11-20", "short") == 0
    media_store.put_item("2026-11-20", "short", 2, {"title": "क्या ज़बरदस्त", "status": "ready", "youtube_id": ""})
    media_store.put_item("2026-11-20", "video", 1, {"title": "v1", "status": "ready", "youtube_id": ""})
    assert media_store.max_index("2026-11-20", "short") == 2
    got = media_store.get_item("2026-11-20", "short", 2)
    assert got["title"] == "क्या ज़बरदस्त"
    media_store.update_item("2026-11-20", "short", 2, youtube_id="abc", status="uploaded")
    items = media_store.list_items("2026-11-20")
    assert [(i["kind"], i["index"]) for i in items] == [("short", 2), ("video", 1)]
    assert items[0]["youtube_id"] == "abc"
    media_store.delete_item("2026-11-20", "video", 1)
    assert media_store.get_item("2026-11-20", "video", 1) is None


def test_publish_without_storage(backend, tmp_path, monkeypatch):
    """publish() indexes a rendered folder even when Supabase Storage isn't configured."""
    from pipeline import media_store
    monkeypatch.setattr(media_store, "enabled", lambda: True)   # index into whichever DB backend is active
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    work = tmp_path / "2026-11-20" / "video_03"
    work.mkdir(parents=True)
    (work / "script.json").write_text(json.dumps({"title": "T", "tags": ["a"]}), encoding="utf-8")
    (work / "final.mp4").write_bytes(b"x")
    media_store.publish(work, "2026-11-20", "video", 3, "18:50")
    it = media_store.get_item("2026-11-20", "video", 3)
    assert it["status"] == "ready" and it["slot"] == "18:50" and it["youtube_id"] == ""
    (work / "youtube_id.txt").write_text("vid123")
    media_store.publish(work, "2026-11-20", "video", 3)
    assert media_store.get_item("2026-11-20", "video", 3)["status"] == "uploaded"
