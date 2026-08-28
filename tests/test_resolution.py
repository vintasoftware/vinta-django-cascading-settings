"""What a setting resolves to, and why."""

from __future__ import annotations

import pytest

from tests.testapp.models import Member, Team
from vinta_django_cascading_settings import (
    LevelNotConfigured,
    SettingLocked,
    annotate_settings,
    explain_setting,
    get_setting,
    get_settings,
    lock_setting,
    set_setting,
    unset_setting,
)

pytestmark = pytest.mark.django_db


def test_an_unset_setting_falls_back_to_the_default(schema, team):
    assert get_setting(team, "support_email", default="none@acme.test") == "none@acme.test"


def test_a_value_set_globally_reaches_every_level(schema, team, member):
    set_setting(None, "support_email", "help@acme.test")

    assert get_setting(team, "support_email") == "help@acme.test"
    assert get_setting(member, "support_email") == "help@acme.test"


def test_the_nearest_level_with_a_value_wins(schema, organization, team, member):
    set_setting(None, "support_email", "help@global.test")
    set_setting(organization, "support_email", "help@acme.test")
    set_setting(team, "support_email", "help@platform.test")

    assert get_setting(organization, "support_email") == "help@acme.test"
    assert get_setting(team, "support_email") == "help@platform.test"
    assert get_setting(member, "support_email") == "help@platform.test"


def test_a_value_set_to_null_stops_the_cascade(schema, organization, team):
    set_setting(organization, "seats", 10)
    set_setting(team, "seats", None)

    assert get_setting(team, "seats", default="fallback") is None
    assert explain_setting(team, "seats").is_set


def test_unsetting_hands_the_key_back_to_the_level_above(schema, organization, team):
    set_setting(organization, "seats", 10)
    set_setting(team, "seats", 3)
    assert get_setting(team, "seats") == 3

    assert unset_setting(team, "seats") is True
    assert get_setting(team, "seats") == 10


def test_a_lock_beats_a_value_set_closer_to_the_object(schema, organization, team, member):
    set_setting(organization, "seats", 10, locked=True)
    set_setting(team, "seats", 99, force=True)

    assert get_setting(team, "seats") == 10
    assert get_setting(member, "seats") == 10
    assert explain_setting(team, "seats").is_locked


def test_the_outermost_lock_wins_when_two_levels_lock_the_same_key(
    schema, organization, team, member
):
    set_setting(organization, "seats", 10, locked=True)
    set_setting(team, "seats", 20, locked=True, force=True)

    assert get_setting(member, "seats") == 10


def test_unlocking_lets_the_level_below_have_its_way(schema, organization, team):
    set_setting(organization, "seats", 10, locked=True)
    set_setting(team, "seats", 3, force=True)
    assert get_setting(team, "seats") == 10

    set_setting(organization, "seats", 10, locked=False)

    assert get_setting(team, "seats") == 3


def test_a_lock_with_nothing_under_it_changes_nothing(schema, organization, team):
    lock_setting(organization, "seats")
    set_setting(team, "seats", 3)

    assert get_setting(team, "seats") == 3


def test_explain_says_which_level_the_value_came_from(schema, organization, team):
    set_setting(organization, "support_email", "help@acme.test")

    resolved = explain_setting(team, "support_email")

    assert resolved.value == "help@acme.test"
    assert resolved.level == "organization"
    assert resolved.schema == "workspace"
    assert resolved.depth == 1
    assert resolved.is_inherited is True
    assert resolved.is_own is False
    assert resolved.object_id == str(organization.pk)


def test_explain_says_when_the_object_set_it_itself(schema, team):
    set_setting(team, "support_email", "help@platform.test")

    resolved = explain_setting(team, "support_email")

    assert resolved.is_own is True
    assert resolved.is_inherited is False
    assert resolved.depth == 0


def test_a_missing_link_in_the_chain_is_simply_skipped(schema, organization, team):
    """A team whose organization is not the one holding the value inherits nothing."""
    set_setting(organization, "seats", 10)
    other = Team.objects.create(
        organization=organization.__class__.objects.create(name="Other"), name="Other"
    )

    assert get_setting(other, "seats") is None
    assert get_setting(team, "seats") == 10


def test_list_values_survive_the_round_trip(schema, organization, team):
    set_setting(organization, "features", ["exports", "sso"])

    assert get_setting(team, "features") == ["exports", "sso"]


def test_get_settings_returns_every_key_that_is_set(schema, organization, team):
    set_setting(organization, "seats", 10)
    set_setting(team, "support_email", "help@platform.test")

    assert get_settings(team) == {"seats": 10, "support_email": "help@platform.test"}


def test_a_model_that_is_not_a_level_says_so(schema, gadget):
    with pytest.raises(LevelNotConfigured):
        get_setting(gadget, "seats")


def test_resolution_is_one_query(schema, organization, team, django_assert_num_queries):
    set_setting(organization, "seats", 10)

    queryset = annotate_settings(Team.objects.filter(pk=team.pk), "seats")
    with django_assert_num_queries(1):
        assert [row.setting_seats for row in queryset] == [10]


def test_settings_can_be_filtered_and_ordered_on(schema, organization, team):
    set_setting(organization, "seats", 10)
    quiet = Team.objects.create(organization=organization, name="Quiet")
    set_setting(quiet, "seats", 1)

    matching = Team.objects.with_settings("seats").filter(setting_seats=10)

    assert list(matching) == [team]
    assert [
        row.setting_seats for row in Team.objects.with_settings("seats").order_by("setting_seats")
    ] == [1, 10]


def test_settings_annotate_across_a_two_hop_chain(schema, organization, member):
    set_setting(organization, "seats", 10)

    rows = annotate_settings(Member.objects.all(), "seats")

    assert [row.setting_seats for row in rows] == [10]


def test_writing_under_a_lock_is_refused(schema, organization, team):
    set_setting(organization, "seats", 10, locked=True)

    with pytest.raises(SettingLocked):
        set_setting(team, "seats", 3)

    assert get_setting(team, "seats") == 10


def test_a_level_with_a_uuid_primary_key_resolves_too(schema, levels, team):
    """The stored holder id and the one the query casts have to agree."""
    from django.contrib.contenttypes.models import ContentType

    from tests.testapp.models import Device
    from vinta_django_cascading_settings.models import SettingsLevel

    SettingsLevel.objects.create(
        key="device",
        content_type=ContentType.objects.get_for_model(Device),
        parent=levels["team"],
        parent_lookup="team",
    )
    device = Device.objects.create(team=team, name="Laptop")
    set_setting(team, "seats", 4)

    assert get_setting(device, "seats") == 4

    set_setting(device, "seats", 1)
    assert get_setting(device, "seats") == 1
    assert get_setting(team, "seats") == 4


def test_a_numeric_setting_can_be_compared_and_summed(schema, organization, team):
    from django.db.models import IntegerField, Sum

    from vinta_django_cascading_settings import SettingValue

    set_setting(organization, "seats", 10)
    small = Team.objects.create(organization=organization, name="Small")
    set_setting(small, "seats", 2)

    seats = SettingValue("seats", output_field=IntegerField())
    rows = Team.objects.annotate(seats=seats)

    assert list(rows.filter(seats__gt=5).values_list("name", flat=True)) == ["Platform"]
    assert rows.aggregate(total=Sum("seats"))["total"] == 12
