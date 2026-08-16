import argparse
import os

from config import BASE_DIR
from pipeline.uploader import YOUTUBE_TOKEN_FILE, _get_service
from pipeline.accounts import add_account


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", default="", help="Account id (slug) — omit to (re)authenticate the default single-account token")
    parser.add_argument("--label", default="", help="Display label for this account (required with --account)")
    parser.add_argument("--locale", default="hi", help="Default locale code for this account (see pipeline/locales.py)")
    args = parser.parse_args()

    if args.account:
        if not args.label:
            parser.error("--label is required when using --account")
        token_file = f"youtube_token_{args.account}.pickle"
        token_path = BASE_DIR / token_file
        if token_path.exists():
            os.remove(token_path)
        print(f"Starting OAuth flow for account '{args.account}'...")
        _get_service(token_file=str(token_path))
        add_account(args.account, args.label, args.locale, token_file)
        print(f"Account '{args.account}' connected -> {token_path}")
    else:
        if YOUTUBE_TOKEN_FILE.exists():
            os.remove(YOUTUBE_TOKEN_FILE)
        print("Starting OAuth flow for the default account...")
        _get_service()
        print(f"Token saved -> {YOUTUBE_TOKEN_FILE}")


if __name__ == "__main__":
    main()
