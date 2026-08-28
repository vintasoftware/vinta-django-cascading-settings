"""The JSON API: what it hands back, and what it refuses."""

from __future__ import annotations

import json

import pytest
from django.urls import reverse

from vinta_django_cascading_settings import get_setting, set_setting

pytestmark = pytest.mark.django_db


def object_url(schema, level, obj):
    return reverse(
        "cascading_settings:object-settings",
        kwargs={"schema": schema, "level": level, "object_id": str(obj.pk)},
    )


def patch(client, url, payload):
    return client.patch(url, data=json.dumps(payload), content_type="application/json")


def test_settings_are_not_public(client, schema, team):
    response = client.get(object_url("workspace", "team", team))

    assert response.status_code == 403


def test_reading_gives_the_plan_and_every_setting(staff_client, schema, organization, team):
    set_setting(organization, "seats", 10)

    response = staff_client.get(object_url("workspace", "team", team))
    payload = response.json()

    assert response.status_code == 200
    assert payload["level"] == "team"
    assert payload["plan"]["questionnaire"] == "workspace"
    assert payload["settings"]["seats"] == {
        "value": 10,
        "isSet": True,
        "isOwn": False,
        "isInherited": True,
        "isLocked": False,
        "source": {
            "level": "organization",
            "scope": "",
            "schema": "workspace",
            "objectId": str(organization.pk),
            "depth": 1,
        },
    }
    assert payload["settings"]["support_email"]["isSet"] is False


def test_writing_records_only_what_it_is_given(staff_client, schema, organization, team):
    set_setting(organization, "seats", 10)

    response = patch(staff_client, object_url("workspace", "team", team), {"values": {"seats": 3}})

    assert response.status_code == 200
    assert response.json()["settings"]["seats"]["isOwn"] is True
    assert get_setting(team, "seats") == 3
    assert get_setting(organization, "seats") == 10


def test_unsetting_hands_the_key_back_to_the_level_above(staff_client, schema, organization, team):
    set_setting(organization, "seats", 10)
    set_setting(team, "seats", 3)

    response = patch(staff_client, object_url("workspace", "team", team), {"unset": ["seats"]})

    assert response.json()["settings"]["seats"]["isInherited"] is True
    assert get_setting(team, "seats") == 10


def test_a_value_the_question_refuses_comes_back_as_422(staff_client, schema, team):
    response = patch(
        staff_client,
        object_url("workspace", "team", team),
        {"values": {"support_email": "not-an-email"}},
    )

    assert response.status_code == 422
    assert response.json()["errors"]["support_email"][0]["errorKey"] == "invalid_email"


def test_writing_under_a_lock_comes_back_as_409(staff_client, schema, organization, team):
    set_setting(organization, "seats", 10, locked=True)

    response = patch(staff_client, object_url("workspace", "team", team), {"values": {"seats": 3}})

    assert response.status_code == 409
    assert "locked" in response.json()["detail"]


def test_a_lock_can_be_set_over_the_api(staff_client, schema, organization, team):
    set_setting(organization, "seats", 10)

    url = object_url("workspace", "organization", organization)
    response = patch(staff_client, url, {"locks": {"seats": True}})

    assert response.json()["settings"]["seats"]["isLocked"] is True
    assert get_setting(team, "seats") == 10


def test_the_global_level_has_its_own_url(staff_client, schema, team):
    url = reverse("cascading_settings:global-settings", kwargs={"schema": "workspace"})

    assert patch(staff_client, url, {"values": {"seats": 7}}).status_code == 200
    assert staff_client.get(url).json()["objectId"] is None
    assert get_setting(team, "seats") == 7


def test_an_unknown_schema_is_a_404(staff_client, schema, team):
    assert staff_client.get(object_url("nonsense", "team", team)).status_code == 404


def test_a_body_that_is_not_json_comes_back_as_400(staff_client, schema, team):
    response = staff_client.patch(
        object_url("workspace", "team", team),
        data="not json",
        content_type="application/json",
    )

    assert response.status_code == 400
