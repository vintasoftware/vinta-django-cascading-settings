"""What type a setting comes back as, and what that lets a query do."""

from __future__ import annotations

import datetime as dt

import pytest
from django.db.models import IntegerField, Sum, TextField

from tests.testapp.models import Team
from vinta_django_cascading_settings import SettingValue, get_setting, set_setting

pytestmark = pytest.mark.django_db


def test_a_whole_number_comes_back_as_an_integer(schema, organization, team):
    set_setting(organization, "seats", 10)

    assert get_setting(team, "seats") == 10
    assert isinstance(get_setting(team, "seats"), int)


def test_a_number_that_is_not_declared_whole_comes_back_as_a_float(schema, team):
    set_setting(team, "sampling_rate", 0.25)

    assert get_setting(team, "sampling_rate") == 0.25
    assert isinstance(get_setting(team, "sampling_rate"), float)


def test_numbers_compare_as_numbers_rather_than_as_json(schema, organization, team):
    set_setting(organization, "seats", 9)
    big = Team.objects.create(organization=organization, name="Big")
    set_setting(big, "seats", 100)

    rows = Team.objects.with_settings("seats")

    # As JSON text, "100" sorts before "9"; as numbers it does not.
    assert list(rows.filter(setting_seats__gt=10).values_list("name", flat=True)) == ["Big"]
    assert [row.name for row in rows.order_by("setting_seats")] == ["Platform", "Big"]


def test_numbers_can_be_aggregated(schema, organization, team):
    set_setting(organization, "seats", 10)
    Team.objects.create(organization=organization, name="Second")

    rows = Team.objects.with_settings("seats")

    assert rows.aggregate(total=Sum("setting_seats"))["total"] == 20


def test_text_comes_back_unquoted_and_compares_as_text(schema, organization, team):
    set_setting(organization, "support_email", "help@acme.test")

    assert get_setting(team, "support_email") == "help@acme.test"
    assert (
        Team.objects.with_settings("support_email")
        .filter(setting_support_email__endswith="@acme.test")
        .count()
        == 1
    )


def test_a_date_comes_back_as_a_date(schema, organization, team):
    set_setting(organization, "renews_on", "2026-09-30")

    assert get_setting(team, "renews_on") == dt.date(2026, 9, 30)
    assert (
        Team.objects.with_settings("renews_on")
        .filter(setting_renews_on__gt=dt.date(2026, 1, 1))
        .count()
        == 1
    )


def test_something_that_is_not_a_scalar_stays_json(schema, organization, team):
    set_setting(organization, "features", ["exports", "sso"])

    assert get_setting(team, "features") == ["exports", "sso"]


def test_a_key_two_schemas_disagree_about_stays_json(
    schema, make_settings_schema, organization, team
):
    from vinta_django_questionnaires.question_types import QuestionType

    make_settings_schema("billing", ["seats"], question_type=QuestionType.FREE_TEXT)
    set_setting(organization, "seats", 10, schema="workspace")

    # Read without saying which schema, the two disagree, so nothing is cast.
    assert get_setting(team, "seats") == 10
    # Read against the one that says it is a number, it is one.
    assert isinstance(get_setting(team, "seats", schema="workspace"), int)


def test_the_caller_can_still_say_what_it_wants(schema, organization, team):
    set_setting(organization, "seats", 10)

    rows = Team.objects.annotate(
        seats=SettingValue("seats", output_field=TextField()),
        whole=SettingValue("seats", output_field=IntegerField()),
    )
    row = rows.values("seats", "whole").get(pk=team.pk)

    assert row["seats"] == "10"
    assert row["whole"] == 10


def test_a_key_nothing_asks_about_resolves_to_nothing(schema, team):
    assert get_setting(team, "nonsense") is None
