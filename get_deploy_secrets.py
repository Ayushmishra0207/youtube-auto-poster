"""
Run this ONCE on your local machine to get the environment variable values
needed for Render deployment.

Usage:
  python get_deploy_secrets.py

Copy the output values into Render → Environment and GitHub → Settings →
Secrets and variables → Actions (see DEPLOY.md). Never paste them into chats,
issues or commits — anyone with YOUTUBE_TOKEN_B64 can post to your channel.
"""
import base64, json, sys
from pathlib import Path

# "→" etc. crashed with UnicodeEncodeError when the output was redirected on Windows (cp1252)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).parent

print("=" * 60)
print("RENDER ENVIRONMENT VARIABLES")
print("Copy each value into Render → your service → Environment")
print("=" * 60)

# ── YOUTUBE_TOKEN_B64 ──────────────────────────────────────────
token_path = BASE / "youtube_token.pickle"
if token_path.exists():
    token_b64 = base64.b64encode(token_path.read_bytes()).decode()
    print(f"\nYOUTUBE_TOKEN_B64=")
    print(token_b64)
else:
    print("\n[!] youtube_token.pickle not found — run setup_auth.py first")

# ── TOPIC_CONFIG_JSON ─────────────────────────────────────────
config_path = BASE / "topic_config.json"
if config_path.exists():
    # Minify it so it fits in one line
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    print(f"\nTOPIC_CONFIG_JSON=")
    print(json.dumps(cfg, ensure_ascii=False))
else:
    print("\n[!] topic_config.json not found")

# ── Reminder for manual keys ─────────────────────────────────
print("\n" + "=" * 60)
print("Also set these (from your .env file / Supabase / GitHub) — see DEPLOY.md:")
print("  Render + GitHub : DATABASE_URL, SUPABASE_URL, SUPABASE_SERVICE_KEY, YOUTUBE_TOKEN_B64,")
print("                    ANTHROPIC_API_KEY, PEXELS_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY")
print("  Render only     : ADMIN_USERNAME, ADMIN_PASSWORD, GITHUB_DISPATCH_TOKEN, FRONTEND_URL")
print("=" * 60)
