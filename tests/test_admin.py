"""The admin settings page: what it shows, and what saving it does."""

from __future__ import annotations

import pytest
from django.urls import reverse

from vinta_django_cascading_settings import explain_setting, get_setting, set_setting

pytestmark = pytest.mark.django_db


def settings_url(obj, name):
    return reverse(f"admin:testapp_{name}_settings", args=[obj.pk])


def test_the_page_shows_what_a_setting_would_be_inherited_as(
    admin_client, schema, organization, team
):
    set_setting(organization, "seats", 10)

    response = admin_client.get(settings_url(team, "team"))

    assert response.status_code == 200
    assert b"Inherited from the &quot;organization&quot; level as 10." in response.content


def test_saving_a_box_records_it_at_this_level(admin_client, schema, organization, team):
    set_setting(organization, "seats", 10)

    response = admin_client.post(
        settings_url(team, "team"),
        {"value_seats": "3", "value_support_email": "", "value_features": ""},
    )

    assert response.status_code == 302
    assert get_setting(team, "seats") == 3


def test_emptying_a_box_hands_the_setting_back(admin_client, schema, organization, team):
    set_setting(organization, "seats", 10)
    set_setting(team, "seats", 3)

    admin_client.post(
        settings_url(team, "team"),
        {"value_seats": "", "value_support_email": "", "value_features": ""},
    )

    assert explain_setting(team, "seats").is_inherited is True
    assert get_setting(team, "seats") == 10


def test_a_box_that_is_not_json_is_reported_on_that_box(admin_client, schema, team):
    response = admin_client.post(
        settings_url(team, "team"),
        {"value_seats": "", "value_support_email": "help@acme.test", "value_features": ""},
    )

    assert response.status_code == 200
    assert b"not valid JSON" in response.content
    assert get_setting(team, "support_email") is None


def test_a_value_the_question_refuses_is_reported_on_that_box(admin_client, schema, team):
    response = admin_client.post(
        settings_url(team, "team"),
        {"value_seats": "", "value_support_email": '"not-an-email"', "value_features": ""},
    )

    assert response.status_code == 200
    assert b"valid email" in response.content.lower() or b"email" in response.content
    assert get_setting(team, "support_email") is None


def test_ticking_the_lock_stops_the_level_below(admin_client, schema, organization, team):
    admin_client.post(
        settings_url(organization, "organization"),
        {
            "value_seats": "10",
            "lock_seats": "on",
            "value_support_email": "",
            "value_features": "",
        },
    )

    assert get_setting(team, "seats") == 10
    assert explain_setting(team, "seats").is_locked is True


def test_the_changelist_links_to_the_settings_page(admin_client, schema, team):
    response = admin_client.get(reverse("admin:testapp_team_changelist"))

    assert settings_url(team, "team").encode() in response.content
