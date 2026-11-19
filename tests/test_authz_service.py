"""Role capability matrix and restriction tests."""

from services.authz_service import (
    Actor,
    Capability,
    Restrictions,
    Role,
    apply_owner_bootstrap,
    can,
)


def test_owner_has_all_capabilities():
    for capability in Capability:
        assert can(Role.OWNER, capability)


def test_streamer_cannot_manage_staff_or_service_bans():
    assert not can(Role.STREAMER, Capability.MANAGE_STAFF)
    assert not can(Role.STREAMER, Capability.MANAGE_SERVICE_BAN)
    assert can(Role.STREAMER, Capability.MANAGE_EDITORS)
    assert can(Role.STREAMER, Capability.EDIT_TABLES)


def test_admin_manages_editors_only():
    assert can(Role.ADMIN, Capability.MANAGE_EDITORS)
    assert not can(Role.ADMIN, Capability.MANAGE_STAFF)
    assert not can(Role.ADMIN, Capability.MANAGE_SERVICE_BAN)


def test_editor_edits_tables_but_cannot_use_admin_commands():
    assert can(Role.EDITOR, Capability.EDIT_TABLES)
    assert not can(Role.EDITOR, Capability.ADMIN_COMMANDS)


def test_twitch_ban_blocks_only_user_recommendations():
    restrictions = Restrictions(twitch_banned=True)
    assert not can(Role.USER, Capability.RECOMMEND, restrictions)
    assert can(Role.EDITOR, Capability.EDIT_TABLES, restrictions)


def test_service_ban_blocks_writes_but_not_owner():
    restrictions = Restrictions(service_banned=True)
    assert not can(Role.EDITOR, Capability.EDIT_TABLES, restrictions)
    assert not can(Role.ADMIN, Capability.ADMIN_COMMANDS, restrictions)
    assert can(Role.OWNER, Capability.MANAGE_STAFF, restrictions)


def test_service_ban_does_not_block_bot_commands():
    actor = Actor(
        user_id=1,
        role=Role.ADMIN,
        restrictions=Restrictions(service_banned=True),
    )
    assert not actor.can(Capability.ADMIN_COMMANDS)
    assert actor.can_command(Capability.ADMIN_COMMANDS)


def test_twitch_ban_still_blocks_bot_recommendations_for_users():
    actor = Actor(
        user_id=1,
        role=Role.USER,
        restrictions=Restrictions(twitch_banned=True),
    )
    assert not actor.can_command(Capability.RECOMMEND)


def test_owner_bootstrap_does_not_read_unloaded_profile_with_login():
    class UserStub:
        id = 1
        twitch_user_id = "137727939"
        role = "owner"

        @property
        def current_profile(self):
            raise AssertionError("current_profile must not be loaded")

    assert not apply_owner_bootstrap(UserStub(), "mishgan_sol")
