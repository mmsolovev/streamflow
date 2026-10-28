"""Encrypt legacy plaintext Twitch tokens in both authorization tables.

Usage:

    python -m database.encrypt_twitch_tokens           # dry run
    python -m database.encrypt_twitch_tokens --apply   # write encrypted values
"""
from __future__ import annotations

import argparse

from sqlalchemy import text

from backend.security.token_crypto import KEY_VERSION, decrypt_token, encrypt_token
from database.db import engine


TABLES = ("twitch_authorizations", "twitch_streamer_authorizations")


def _rows(conn, table: str):
    return conn.execute(
        text(
            f"""
            SELECT user_id, access_token, refresh_token,
                   access_token_encrypted, refresh_token_encrypted
            FROM {table}
            WHERE access_token IS NOT NULL OR refresh_token IS NOT NULL
            """
        )
    ).all()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    total = 0
    with engine.begin() as conn:
        for table in TABLES:
            rows = _rows(conn, table)
            print(f"{table}: plaintext rows = {len(rows)}")
            for row in rows:
                access = row.access_token_encrypted or (
                    encrypt_token(row.access_token) if row.access_token else None
                )
                refresh = row.refresh_token_encrypted or (
                    encrypt_token(row.refresh_token) if row.refresh_token else None
                )
                if access:
                    assert decrypt_token(access)
                if refresh:
                    assert decrypt_token(refresh)
                print(f"  user_id={row.user_id}: access={'yes' if access else 'no'}, refresh={'yes' if refresh else 'no'}")
                if not args.apply:
                    continue
                conn.execute(
                    text(
                        f"""
                        UPDATE {table}
                        SET access_token_encrypted = :access,
                            refresh_token_encrypted = :refresh,
                            access_token = NULL,
                            refresh_token = NULL,
                            key_version = :key_version
                        WHERE user_id = :user_id
                        """
                    ),
                    {
                        "access": access,
                        "refresh": refresh,
                        "key_version": KEY_VERSION,
                        "user_id": row.user_id,
                    },
                )
                total += 1

    if not args.apply:
        print("\nЭто dry-run. Для применения добавьте --apply.")
        return
    print(f"\nЗашифровано строк: {total}")


if __name__ == "__main__":
    main()
