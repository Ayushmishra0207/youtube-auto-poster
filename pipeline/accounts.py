"""
Multi-account registry. Each connected YouTube channel is an Account with
its own OAuth token, topic/Shorts config, and output/state directory —
see docs/superpowers/specs/2026-08-16-multi-account-support-design.md.
"""
import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import BASE_DIR, OUTPUT_DIR

IST = timezone(timedelta(hours=5, minutes=30))

ACCOUNTS_FILE = BASE_DIR / "accounts.json"
ACCOUNTS_DIR = BASE_DIR / "accounts"

_DEFAULT_TOPIC_CONFIG = {"slots": [], "categories": {}}
_DEFAULT_SHORTS_CONFIG = {
    "shorts_per_day": 10,
    "feeds": ["india", "world", "business"],
    "content_types_enabled": [
        "news", "funny", "story", "short_story", "motivational", "entertainment",
        "bollywood", "history", "imagination", "devotional", "sports", "tech",
        "comedy_skit", "horror_mystery", "books", "poetry",
    ],
    "upload_slots": [
        "08:00", "09:30", "11:00", "12:30", "13:30",
        "15:30", "17:30", "19:15", "20:30", "21:45",
    ],
}


@dataclass
class Account:
    id: str
    label: str
    locale: str
    token_file: str
    enabled: bool = True
    created_at: str = ""

    @property
    def token_path(self) -> Path:
        return BASE_DIR / self.token_file

    @property
    def dir(self) -> Path:
        return ACCOUNTS_DIR / self.id

    @property
    def topic_config_path(self) -> Path:
        return self.dir / "topic_config.json"

    @property
    def shorts_config_path(self) -> Path:
        return self.dir / "shorts_config.json"

    @property
    def output_dir(self) -> Path:
        return Path(OUTPUT_DIR) / self.id


def ensure_default_account() -> None:
    """
    Idempotent first-run migration: if accounts.json doesn't exist yet,
    wrap today's single-account setup (root topic_config.json,
    youtube_token.pickle, output/<date>/...) into one account called
    "default", so the channel that's already running keeps working with
    zero manual steps.
    """
    if ACCOUNTS_FILE.exists():
        return

    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    default_dir = ACCOUNTS_DIR / "default"
    default_dir.mkdir(parents=True, exist_ok=True)

    root_topic_config = BASE_DIR / "topic_config.json"
    if root_topic_config.exists():
        shutil.copy(root_topic_config, default_dir / "topic_config.json")
    else:
        (default_dir / "topic_config.json").write_text(
            json.dumps(_DEFAULT_TOPIC_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    (default_dir / "shorts_config.json").write_text(
        json.dumps(_DEFAULT_SHORTS_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    for state_name in ("longform_topic_history.json", "shorts_topic_history.json", "youtube_playlists.json"):
        root_state = BASE_DIR / state_name
        if root_state.exists():
            shutil.copy(root_state, default_dir / state_name)

    old_output = Path(OUTPUT_DIR)
    new_output = Path(OUTPUT_DIR) / "default"
    if old_output.exists():
        new_output.mkdir(parents=True, exist_ok=True)
        for dated_dir in old_output.iterdir():
            if dated_dir.is_dir() and dated_dir.name != "default":
                shutil.move(str(dated_dir), str(new_output / dated_dir.name))

    account = Account(
        id="default", label="Default Channel", locale="hi",
        token_file="youtube_token.pickle", enabled=True,
        created_at=datetime.now(IST).strftime("%Y-%m-%d"),
    )
    save_accounts([account])


def load_accounts() -> list[Account]:
    ensure_default_account()
    data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
    return [Account(**a) for a in data["accounts"]]


def save_accounts(accounts: list[Account]) -> None:
    ACCOUNTS_FILE.write_text(
        json.dumps({"accounts": [asdict(a) for a in accounts]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_account(account_id: str) -> "Account | None":
    for a in load_accounts():
        if a.id == account_id:
            return a
    return None


def enabled_accounts() -> list[Account]:
    return [a for a in load_accounts() if a.enabled]


def set_account_enabled(account_id: str, enabled: bool) -> None:
    accounts = load_accounts()
    for a in accounts:
        if a.id == account_id:
            a.enabled = enabled
            break
    else:
        raise ValueError(f"Unknown account '{account_id}'")
    save_accounts(accounts)


def add_account(account_id: str, label: str, locale: str, token_file: str) -> Account:
    accounts = load_accounts()
    if any(a.id == account_id for a in accounts):
        raise ValueError(f"Account '{account_id}' already exists")

    account = Account(
        id=account_id, label=label, locale=locale, token_file=token_file,
        enabled=True, created_at=datetime.now(IST).strftime("%Y-%m-%d"),
    )
    accounts.append(account)
    save_accounts(accounts)

    account.dir.mkdir(parents=True, exist_ok=True)
    account.topic_config_path.write_text(
        json.dumps(_DEFAULT_TOPIC_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    account.shorts_config_path.write_text(
        json.dumps(_DEFAULT_SHORTS_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return account
