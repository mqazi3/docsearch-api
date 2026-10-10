"""Manage API keys.

python -m app.cli create-key --name "my laptop" --role admin
python -m app.cli list-keys
python -m app.cli revoke-key dsk_a1B2c3D4
"""

import argparse
from datetime import UTC, datetime

from sqlalchemy import select

from app.auth import create_api_key
from app.db import SessionLocal
from app.models import ApiKey, ApiKeyRole


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create-key", help="create a new API key")
    create.add_argument("--name", required=True)
    create.add_argument("--role", choices=[r.value for r in ApiKeyRole], default="reader")

    commands.add_parser("list-keys", help="list keys (never shows the secret)")

    revoke = commands.add_parser("revoke-key", help="revoke a key by its prefix")
    revoke.add_argument("prefix")

    args = parser.parse_args()
    with SessionLocal() as db:
        if args.command == "create-key":
            key, raw_key = create_api_key(db, args.name, args.role)
            print(f"Created {key.role} key '{key.name}' ({key.prefix}...)\n")
            print(f"    {raw_key}\n")
            print("Copy it now. It is stored only as a hash and cannot be shown again.")

        elif args.command == "list-keys":
            for key in db.scalars(select(ApiKey).order_by(ApiKey.created_at)):
                status = "revoked" if key.revoked_at else "active"
                last_used = (
                    key.last_used_at.isoformat(timespec="minutes") if key.last_used_at else "never"
                )
                print(
                    f"{key.prefix}...  {key.role:<6}  {status:<7}  "
                    f"last used {last_used}  {key.name}"
                )

        elif args.command == "revoke-key":
            matches = db.scalars(
                select(ApiKey).where(ApiKey.prefix == args.prefix, ApiKey.revoked_at.is_(None))
            ).all()
            if len(matches) != 1:
                raise SystemExit(
                    f"Expected one active key with prefix {args.prefix}; found {len(matches)}"
                )
            matches[0].revoked_at = datetime.now(UTC)
            db.commit()
            print(f"Revoked {args.prefix}...")


if __name__ == "__main__":
    main()
