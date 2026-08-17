"""Per-account Shorts settings — feeds, enabled content-types, daily slots.
Mirrors topic_config.json's role for long-form, but for Shorts."""
import json

from pipeline.accounts import Account, _DEFAULT_SHORTS_CONFIG


def load_shorts_config(account: Account) -> dict:
    if not account.shorts_config_path.exists():
        save_shorts_config(account, dict(_DEFAULT_SHORTS_CONFIG))
    return json.loads(account.shorts_config_path.read_text(encoding="utf-8"))


def save_shorts_config(account: Account, cfg: dict) -> None:
    account.dir.mkdir(parents=True, exist_ok=True)
    account.shorts_config_path.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
