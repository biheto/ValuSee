from pathlib import Path
from tempfile import TemporaryDirectory

from app.auth.service import AuthStore


def test_family_invitation_requires_recipient_confirmation_and_roles_control_writes():
    with TemporaryDirectory() as tmp:
        store = AuthStore(Path(tmp) / "family.db")
        owner = store.register("owner@example.com", "strong-password", "Owner")
        member = store.register("member@example.com", "strong-password", "Member")
        outsider = store.register("other@example.com", "strong-password", "Other")
        family = store.create_family(owner["user_id"], "Home")
        invitation = store.create_family_invitation(owner["user_id"], family["family_id"], member["email"])

        assert store.list_family_members(owner["user_id"], family["family_id"])[0]["role"] == "owner"
        assert store.list_family_invitations(member["user_id"])[0]["invitation_id"] == invitation["invitation_id"]
        store.respond_family_invitation(member["user_id"], invitation["invitation_id"], True)
        assert len(store.list_family_members(member["user_id"], family["family_id"])) == 2
        try:
            store.save_family_asset(member["user_id"], family["family_id"], {"name": "Coffee machine"})
        except ValueError:
            pass
        else:
            raise AssertionError("regular members must not edit family assets")

        store.set_family_member_role(owner["user_id"], family["family_id"], member["user_id"], "editor")
        asset = store.save_family_asset(member["user_id"], family["family_id"], {"name": "Coffee machine", "category": "Appliance", "warranty_deadline": "2028-01-01"})
        assert store.list_family_assets(owner["user_id"], family["family_id"])[0]["asset_id"] == asset["asset_id"]
        budget = store.save_family_budget(member["user_id"], family["family_id"], {"monthly_budget": 3000, "annual_budget": 24000, "currency": "cny"})
        assert budget["currency"] == "CNY" and budget["monthly_budget"] == 3000
        try:
            store.list_family_assets(outsider["user_id"], family["family_id"])
        except ValueError:
            pass
        else:
            raise AssertionError("outsiders must not read family assets")


def test_declined_family_invitation_does_not_add_member():
    with TemporaryDirectory() as tmp:
        store = AuthStore(Path(tmp) / "family.db")
        owner = store.register("owner@example.com", "strong-password", "Owner")
        member = store.register("member@example.com", "strong-password", "Member")
        family = store.create_family(owner["user_id"], "Home")
        invitation = store.create_family_invitation(owner["user_id"], family["family_id"], member["email"])
        assert store.respond_family_invitation(member["user_id"], invitation["invitation_id"], False)["status"] == "declined"
        assert len(store.list_family_members(owner["user_id"], family["family_id"])) == 1
