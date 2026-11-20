"""
Check the Supabase setup before going live (reads .env.cloud; never prints keys).

  py check_cloud.py        (needs psycopg — Python ≤3.13, or the same check runs in CI)

Checks: DATABASE_URL shape → Postgres connection + tables → Storage bucket
upload / signed link / delete.
"""
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).parent
ENV_FILE = ROOT / ".env.cloud"


def ok(msg):
    print(f"  [ok]   {msg}")


def fail(msg, hint=""):
    print(f"  [FAIL] {msg}")
    if hint:
        print(f"         → {hint}")
    sys.exit(1)


def _discover_pooler_url(vals: dict) -> str:
    """Session pooler URI = postgres.<ref>:<password>@aws-<n>-<region>.pooler.supabase.com:5432.
    Try the known host variants (Supabase uses aws-0 or aws-1 depending on project age)."""
    from urllib.parse import quote

    import psycopg
    ref = urlparse(vals["SUPABASE_URL"]).hostname.split(".")[0]
    regions = [r for r in [vals.get("SUPABASE_REGION", ""), "ap-southeast-1", "ap-south-1"] if r]
    pw = quote(vals["SUPABASE_DB_PASSWORD"], safe="")
    last = ""
    for region in dict.fromkeys(regions):
        for n in (0, 1):
            url = f"postgresql://postgres.{ref}:{pw}@aws-{n}-{region}.pooler.supabase.com:5432/postgres"
            try:
                psycopg.connect(url, connect_timeout=10, prepare_threshold=None).close()
                return url
            except Exception as e:
                last = str(e).split("\n")[0]
                if "password authentication failed" in last:
                    fail("Supabase rejected the database password",
                         "check SUPABASE_DB_PASSWORD, or reset it: Project Settings → Database")
    fail(f"couldn't reach the Session pooler ({last})",
         "copy the URI from Connect → Direct → Session pooler into DATABASE_URL instead")


def _write_env_value(key: str, value: str) -> None:
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    out, done = [], False
    for line in lines:
        if line.startswith(f"{key}="):
            out.append(f"{key}={value}")
            done = True
        else:
            out.append(line)
    if not done:
        out.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")


def main():
    from dotenv import dotenv_values
    if not ENV_FILE.exists():
        fail(".env.cloud not found", "create it next to this script (see DEPLOY.md)")
    vals = {k: (v or "").strip() for k, v in dotenv_values(ENV_FILE).items()}
    if not vals.get("DATABASE_URL") and vals.get("SUPABASE_DB_PASSWORD"):
        print("0. Finding the Session pooler address from the database password")
        vals["DATABASE_URL"] = _discover_pooler_url(vals)
        _write_env_value("DATABASE_URL", vals["DATABASE_URL"])
        ok("found it — saved DATABASE_URL into .env.cloud")
    for k in ("SUPABASE_URL", "DATABASE_URL", "SUPABASE_SERVICE_KEY"):
        if not vals.get(k):
            fail(f"{k} is empty in .env.cloud")
        os.environ[k] = vals[k]

    print("1. DATABASE_URL")
    u = urlparse(vals["DATABASE_URL"])
    if u.scheme not in ("postgresql", "postgres"):
        fail("doesn't start with postgresql://", "copy the URI from Supabase → Connect → Session pooler")
    if "[YOUR-PASSWORD]" in vals["DATABASE_URL"] or not u.password:
        fail("password missing", "replace [YOUR-PASSWORD] with your database password (no brackets)")
    host = u.hostname or ""
    if host.startswith("db.") and host.endswith(".supabase.co"):
        fail(f"this is the Direct connection ({host}) — IPv6-only, Render/GitHub can't reach it",
             "use Connect → Session pooler instead (host ends with pooler.supabase.com)")
    if "pooler.supabase.com" in host and u.port == 6543:
        print("  [warn] port 6543 is the Transaction pooler — works, but Session pooler (5432) is recommended")
    ok(f"format looks right (host {host}, port {u.port})")

    print("2. Database")
    try:
        import db
        db.init_db()
        with db.db_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM users")
            n = cur.fetchone()["n"]
    except ImportError as e:
        fail(f"Postgres driver missing ({e})", "pip install \"psycopg[binary]\" (needs Python ≤3.13)")
    except Exception as e:
        msg = str(e).split("\n")[0]
        hint = "check the password" if "password" in msg.lower() else "check the URI from Connect → Session pooler"
        fail(f"could not connect: {msg}", hint)
    ok(f"connected, tables ready (users: {n})")

    print("3. Storage")
    try:
        import requests
        from pipeline import media_store
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "check.txt"
            f.write_text("supabase check", encoding="utf-8")
            key = media_store.upload(f, "_check/check.txt", "text/plain")
            url = media_store.signed_url(key, expires_s=60)
            got = requests.get(url, timeout=30)
            if got.status_code != 200 or got.text != "supabase check":
                fail(f"signed link didn't return the file (HTTP {got.status_code})")
            media_store.remove([key])
    except SystemExit:
        raise
    except Exception as e:
        msg = str(e).split("\n")[0]
        hint = ("use the *secret* key (sb_secret_…) or legacy service_role, not the publishable/anon key"
                if any(c in msg for c in ("401", "403", "Unauthorized", "signature")) else "")
        fail(f"storage error: {msg}", hint)
    ok(f"bucket '{media_store.BUCKET}' ready — upload, signed link and delete all work")

    print("\nAll good — use these same three values in Render and GitHub (DEPLOY.md steps 4-5).")


if __name__ == "__main__":
    main()
