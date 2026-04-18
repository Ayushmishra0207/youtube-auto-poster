"""
Run this ONCE on your local machine to get the environment variable values
needed for Render deployment.

Usage:
  python get_deploy_secrets.py

Copy the output values into Render → Environment Variables.
"""
import base64, json, sys
from pathlib import Path

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
print("Also set these manually in Render (from your .env file):")
print("  ANTHROPIC_API_KEY   = sk-ant-...")
print("  PEXELS_API_KEY      = your key (optional)")
print("=" * 60)
print("\nDone. Paste the values above into Render dashboard.")
