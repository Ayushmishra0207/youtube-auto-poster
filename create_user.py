"""
Create a login user for the dashboard. There is no public signup — you
create accounts for yourself/teammates with this script.

Usage:
  python create_user.py --username alice --password "correct horse battery staple"
"""
import argparse
import getpass

import sys

from auth import create_user
from db import IntegrityError, init_db


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", default="", help="Omit to be prompted (hidden input)")
    args = parser.parse_args()

    password = args.password or getpass.getpass("Password: ")
    if not password:
        print("Password cannot be empty.")
        sys.exit(1)

    init_db()
    try:
        user_id = create_user(args.username, password)
    except IntegrityError:
        print(f"Username '{args.username}' already exists.")
        sys.exit(1)

    print(f"Created user '{args.username}' (id={user_id})")


if __name__ == "__main__":
    main()
