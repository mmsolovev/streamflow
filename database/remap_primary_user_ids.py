"""One-off maintenance: remap primary users to stable low IDs.

Desired result:

    mishgan_sol (Twitch 137727939) -> users.id = 1
    tabula      (Twitch 600513126) -> users.id = 2
    twitch      (Twitch 544406602) -> users.id = 3

The script is intentionally generic: it discovers all foreign keys that point
to `users.id` in PostgreSQL and updates every referencing row, instead of
hardcoding table/column names. Rows that already occupy target IDs are moved to
fresh IDs first.

Usage:

    python -m database.remap_primary_user_ids            # dry run
    python -m database.remap_primary_user_ids --apply    # apply changes
    python -m database.remap_primary_user_ids --apply --yes

Run it before applying the roles/permissions migrations.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

from database.db import engine


OWNER_TWITCH_ID = "137727939"
STREAMER_TWITCH_ID = "600513126"
PSEUDO_TWITCH_ID = "544406602"

DESIRED = (
    (OWNER_TWITCH_ID, "mishgan_sol", 1),
    (STREAMER_TWITCH_ID, "tabula", 2),
    (PSEUDO_TWITCH_ID, "twitch", 3),
)


@dataclass(frozen=True)
class UserRef:
    id: int
    twitch_user_id: str | None
    login: str | None


@dataclass(frozen=True)
class Move:
    old_id: int
    new_id: int
    twitch_user_id: str | None
    login: str | None


def _q(conn: Connection, name: str) -> str:
    return conn.dialect.identifier_preparer.quote(name)


def _qualified(conn: Connection, schema: str, table: str) -> str:
    preparer = conn.dialect.identifier_preparer
    return f"{preparer.quote_schema(schema)}.{preparer.quote(table)}"


def _load_users(conn: Connection) -> dict[int, UserRef]:
    rows = conn.execute(
        text(
            """
            SELECT u.id, u.twitch_user_id, p.login
            FROM users u
            LEFT JOIN user_profiles p
              ON p.user_id = u.id AND p.is_current IS TRUE
            ORDER BY u.id
            """
        )
    ).all()
    return {
        int(row.id): UserRef(
            id=int(row.id),
            twitch_user_id=row.twitch_user_id,
            login=row.login,
        )
        for row in rows
    }


def _resolve_desired(users: dict[int, UserRef]) -> dict[int, UserRef]:
    by_twitch_id = {
        user.twitch_user_id: user
        for user in users.values()
        if user.twitch_user_id
    }
    resolved: dict[int, UserRef] = {}
    missing: list[str] = []
    for twitch_id, login, _target_id in DESIRED:
        user = by_twitch_id.get(twitch_id)
        if user is None:
            missing.append(f"{login} (twitch_user_id={twitch_id})")
            continue
        resolved[user.id] = user
    if missing:
        raise SystemExit("Не найдены пользователи: " + ", ".join(missing))
    return resolved


def build_moves(users: dict[int, UserRef]) -> list[Move]:
    """Build a collision-free move plan.

    Target IDs may be occupied by unrelated users. Such users are moved to
    fresh IDs first. Desired users that are not at their target are moved to a
    temporary fresh ID and then to the final target, which also handles cycles.
    """
    desired = _resolve_desired(users)
    desired_by_twitch = {user.twitch_user_id: user for user in desired.values()}
    target_by_twitch = {twitch_id: target_id for twitch_id, _login, target_id in DESIRED}

    next_id = max(users, default=0) + 1
    reserved = set(users) | set(target_by_twitch.values())
    moves: list[Move] = []

    def fresh_id() -> int:
        nonlocal next_id
        while next_id in reserved:
            next_id += 1
        value = next_id
        reserved.add(value)
        next_id += 1
        return value

    # 1. Free target IDs from unrelated users.
    for twitch_id, _login, target_id in DESIRED:
        occupant = users.get(target_id)
        if occupant is None:
            continue
        if occupant.twitch_user_id == twitch_id:
            continue
        new_id = fresh_id()
        moves.append(Move(occupant.id, new_id, occupant.twitch_user_id, occupant.login))

    # 2. Move desired users to temporary fresh IDs (except those already at target).
    temp_ids: dict[str, int] = {}
    for twitch_id, _login, target_id in DESIRED:
        user = desired_by_twitch[twitch_id]
        if user.id == target_id:
            continue
        new_id = fresh_id()
        temp_ids[twitch_id] = new_id
        moves.append(Move(user.id, new_id, user.twitch_user_id, user.login))

    # 3. Move desired users from temporary IDs to final targets.
    for twitch_id, _login, target_id in DESIRED:
        temp_id = temp_ids.get(twitch_id)
        if temp_id is None:
            continue
        moves.append(
            Move(
                temp_id,
                target_id,
                desired_by_twitch[twitch_id].twitch_user_id,
                desired_by_twitch[twitch_id].login,
            )
        )

    return moves


def _user_columns(conn: Connection) -> list[str]:
    rows = conn.execute(
        text(
            """
            SELECT a.attname
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = 'users'
              AND n.nspname = current_schema()
              AND a.attnum > 0
              AND NOT a.attisdropped
            ORDER BY a.attnum
            """
        )
    ).all()
    columns = [row.attname for row in rows]
    if not columns:
        raise SystemExit("Не удалось прочитать колонки таблицы users")
    return columns


def _user_fk_columns(conn: Connection) -> list[tuple[str, str, str]]:
    """Return (schema, table, column) for every single-column FK to users.id."""
    rows = conn.execute(
        text(
            """
            SELECT n.nspname AS schema_name,
                   c.relname AS table_name,
                   a.attname AS column_name,
                   array_length(con.conkey, 1) AS column_count
            FROM pg_constraint con
            JOIN pg_class c ON c.oid = con.conrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS cols(attnum, ord)
              ON TRUE
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = cols.attnum
            WHERE con.contype = 'f'
              AND con.confrelid = 'users'::regclass
            ORDER BY n.nspname, c.relname, a.attname
            """
        )
    ).all()
    result: list[tuple[str, str, str]] = []
    for row in rows:
        if row.column_count != 1:
            raise SystemExit(
                "Обнаружен составной FK на users.id: "
                f"{row.schema_name}.{row.table_name}.{row.column_name}. "
                "Скрипт поддерживает только одиночные FK."
            )
        result.append((row.schema_name, row.table_name, row.column_name))
    return result


def _move_user(
    conn: Connection,
    move: Move,
    columns: list[str],
    fk_columns: list[tuple[str, str, str]],
) -> None:
    old_exists = conn.execute(
        text(f"SELECT 1 FROM {_q(conn, 'users')} WHERE id = :id"),
        {"id": move.old_id},
    ).first()
    if old_exists is None:
        raise SystemExit(f"Пользователь id={move.old_id} не найден")
    new_exists = conn.execute(
        text(f"SELECT 1 FROM {_q(conn, 'users')} WHERE id = :id"),
        {"id": move.new_id},
    ).first()
    if new_exists is not None:
        raise SystemExit(f"Целевой id={move.new_id} уже занят")

    insert_columns = [column for column in columns if column not in {"id", "twitch_user_id"}]
    quoted_columns = ", ".join(_q(conn, column) for column in insert_columns)
    select_columns = ", ".join(_q(conn, column) for column in insert_columns)
    conn.execute(
        text(
            f"""
            INSERT INTO {_q(conn, 'users')} (id, {quoted_columns}, twitch_user_id)
            SELECT :new_id, {select_columns}, NULL
            FROM {_q(conn, 'users')}
            WHERE id = :old_id
            """
        ),
        {"new_id": move.new_id, "old_id": move.old_id},
    )

    for schema, table, column in fk_columns:
        conn.execute(
            text(
                f"UPDATE {_qualified(conn, schema, table)} "
                f"SET {_q(conn, column)} = :new_id "
                f"WHERE {_q(conn, column)} = :old_id"
            ),
            {"new_id": move.new_id, "old_id": move.old_id},
        )

    conn.execute(
        text(f"DELETE FROM {_q(conn, 'users')} WHERE id = :old_id"),
        {"old_id": move.old_id},
    )

    if move.twitch_user_id:
        conn.execute(
            text(f"UPDATE {_q(conn, 'users')} SET twitch_user_id = :twitch_id WHERE id = :id"),
            {"twitch_id": move.twitch_user_id, "id": move.new_id},
        )


def _reset_sequence(conn: Connection) -> None:
    sequence = conn.execute(
        text("SELECT pg_get_serial_sequence('users', 'id')")
    ).scalar_one()
    if not sequence:
        return
    conn.execute(
        text("SELECT setval(:sequence, COALESCE((SELECT MAX(id) FROM users), 1), true)"),
        {"sequence": sequence},
    )


def _print_plan(moves: list[Move]) -> None:
    if not moves:
        print("Изменения не требуются: нужные пользователи уже имеют id 1/2/3.")
        return
    print("План перенумерации:")
    for move in moves:
        login = move.login or "?"
        print(f"  users.id {move.old_id} -> {move.new_id}  ({login})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="применить изменения")
    parser.add_argument("--yes", action="store_true", help="не спрашивать подтверждение")
    args = parser.parse_args()

    with engine.begin() as conn:
        users = _load_users(conn)
        moves = build_moves(users)
        _print_plan(moves)
        if not args.apply or not moves:
            if not args.apply:
                print("\nЭто dry-run. Для применения добавьте --apply.")
            return

        if not args.yes:
            answer = input("Применить изменения? Введите 'yes': ").strip().casefold()
            if answer != "yes":
                print("Отменено.")
                return

        columns = _user_columns(conn)
        fk_columns = _user_fk_columns(conn)
        print(f"Найдено FK-колонок на users.id: {len(fk_columns)}")

        for move in moves:
            print(f"  moving {move.old_id} -> {move.new_id}")
            _move_user(conn, move, columns, fk_columns)
        _reset_sequence(conn)

    print("\nГотово.")


if __name__ == "__main__":
    main()
