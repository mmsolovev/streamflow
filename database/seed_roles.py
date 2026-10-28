"""One-off seed of project roles from the legacy env/login lists.

Run after `alembic upgrade head` (revision 0014) and before dropping the legacy
`users.is_admin` column.

Usage:

    python -m database.seed_roles           # dry run
    python -m database.seed_roles --apply   # write roles
"""
from __future__ import annotations

import argparse

from sqlalchemy import text

from config.settings import (
    ALLOWED_USERS,
    OWNER_TWITCH_LOGIN,
    OWNER_TWITCH_USER_ID,
    RECOMMENDATIONS_STREAMER_LOGIN,
)
from database.db import engine


EXTRA_EDITORS = {"orfeylefontu"}


def _normalize(value: str | None) -> str:
    return (value or "").strip().casefold()


def _desired_roles(rows) -> dict[int, tuple[str, str]]:
    by_login = {_normalize(row.login): row for row in rows if row.login}
    by_twitch_id = {str(row.twitch_user_id): row for row in rows if row.twitch_user_id}
    desired: dict[int, tuple[str, str]] = {}

    owner_login = _normalize(OWNER_TWITCH_LOGIN)
    owner_twitch_id = (OWNER_TWITCH_USER_ID or "").strip()
    owner = by_twitch_id.get(owner_twitch_id) or by_login.get(owner_login)
    if owner is None:
        raise SystemExit(
            f"Не найден владелец (twitch_user_id={owner_twitch_id}, login={owner_login})"
        )
    desired[int(owner.id)] = ("owner", "owner")

    streamer_login = _normalize(RECOMMENDATIONS_STREAMER_LOGIN)
    streamer = by_login.get(streamer_login)
    if streamer is not None:
        desired[int(streamer.id)] = ("streamer", "primary streamer")

    editor_logins = {_normalize(login) for login in ALLOWED_USERS} | {
        _normalize(login) for login in EXTRA_EDITORS
    }
    for row in rows:
        if _normalize(row.login) in editor_logins:
            desired.setdefault(int(row.id), ("editor", "legacy ALLOWED_USERS"))

    for row in rows:
        if row.is_admin and int(row.id) not in desired:
            desired[int(row.id)] = ("admin", "legacy is_admin")

    return desired


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT u.id, u.twitch_user_id, u.is_admin, u.role, p.login
                FROM users u
                LEFT JOIN user_profiles p
                  ON p.user_id = u.id AND p.is_current IS TRUE
                ORDER BY u.id
                """
            )
        ).all()
        desired = _desired_roles(rows)
        changes = []
        for row in rows:
            target = desired.get(int(row.id))
            if target is None:
                continue
            role, reason = target
            if row.role == role:
                continue
            changes.append((int(row.id), row.login or "?", row.role, role, reason))

        if not changes:
            print("Роли уже соответствуют ожидаемым.")
            return

        print("План изменения ролей:")
        for user_id, login, old_role, new_role, reason in changes:
            print(f"  {user_id:>5}  {login:<28} {old_role:>8} -> {new_role:<8}  ({reason})")

        if not args.apply:
            print("\nЭто dry-run. Для применения добавьте --apply.")
            return

        for user_id, _login, _old_role, new_role, _reason in changes:
            conn.execute(
                text("UPDATE users SET role = :role WHERE id = :user_id"),
                {"role": new_role, "user_id": user_id},
            )

    print(f"\nОбновлено ролей: {len(changes)}")


if __name__ == "__main__":
    main()
