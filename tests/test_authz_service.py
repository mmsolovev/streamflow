"""Role capability matrix and restriction tests."""
import unittest

from services.authz_service import (
    Actor,
    Capability,
    Restrictions,
    Role,
    apply_owner_bootstrap,
    can,
)


class AuthzMatrixTests(unittest.TestCase):
    def test_owner_has_all_capabilities(self):
        for capability in Capability:
            self.assertTrue(can(Role.OWNER, capability))

    def test_streamer_cannot_manage_staff_or_service_bans(self):
        self.assertFalse(can(Role.STREAMER, Capability.MANAGE_STAFF))
        self.assertFalse(can(Role.STREAMER, Capability.MANAGE_SERVICE_BAN))
        self.assertTrue(can(Role.STREAMER, Capability.MANAGE_EDITORS))
        self.assertTrue(can(Role.STREAMER, Capability.EDIT_TABLES))

    def test_admin_manages_editors_only(self):
        self.assertTrue(can(Role.ADMIN, Capability.MANAGE_EDITORS))
        self.assertFalse(can(Role.ADMIN, Capability.MANAGE_STAFF))
        self.assertFalse(can(Role.ADMIN, Capability.MANAGE_SERVICE_BAN))

    def test_editor_edits_tables_but_cannot_use_admin_commands(self):
        self.assertTrue(can(Role.EDITOR, Capability.EDIT_TABLES))
        self.assertFalse(can(Role.EDITOR, Capability.ADMIN_COMMANDS))

    def test_twitch_ban_blocks_only_user_recommendations(self):
        restrictions = Restrictions(twitch_banned=True)
        self.assertFalse(can(Role.USER, Capability.RECOMMEND, restrictions))
        self.assertTrue(can(Role.EDITOR, Capability.EDIT_TABLES, restrictions))

    def test_service_ban_blocks_writes_but_not_owner(self):
        restrictions = Restrictions(service_banned=True)
        self.assertFalse(can(Role.EDITOR, Capability.EDIT_TABLES, restrictions))
        self.assertFalse(can(Role.ADMIN, Capability.ADMIN_COMMANDS, restrictions))
        self.assertTrue(can(Role.OWNER, Capability.MANAGE_STAFF, restrictions))

    def test_service_ban_does_not_block_bot_commands(self):
        actor = Actor(
            user_id=1,
            role=Role.ADMIN,
            restrictions=Restrictions(service_banned=True),
        )
        self.assertFalse(actor.can(Capability.ADMIN_COMMANDS))
        self.assertTrue(actor.can_command(Capability.ADMIN_COMMANDS))

    def test_twitch_ban_still_blocks_bot_recommendations_for_users(self):
        actor = Actor(
            user_id=1,
            role=Role.USER,
            restrictions=Restrictions(twitch_banned=True),
        )
        self.assertFalse(actor.can_command(Capability.RECOMMEND))

    def test_owner_bootstrap_does_not_read_unloaded_profile_with_login(self):
        class UserStub:
            id = 1
            twitch_user_id = "137727939"
            role = "owner"

            @property
            def current_profile(self):
                raise AssertionError("current_profile must not be loaded")

        self.assertFalse(apply_owner_bootstrap(UserStub(), "mishgan_sol"))


if __name__ == "__main__":
    unittest.main()
