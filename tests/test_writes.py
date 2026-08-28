"""Recording values at one level, and what is refused."""

from __future__ import annotations

import pytest
from vinta_django_questionnaires.models import Answer

from vinta_django_cascading_settings import (
    AmbiguousSetting,
    LevelNotAllowed,
    SettingsValidationError,
    UnknownSetting,
    explain_setting,
    get_setting,
    get_settings,
    set_setting,
    set_settings,
    unset_setting,
)
from vinta_django_cascading_settings.models import ScopedSettings

pytestmark = pytest.mark.django_db


def test_overriding_one_setting_leaves_the_others_inherited(schema, organization, team):
    set_settings(organization, {"seats": 10, "support_email": "help@acme.test"})
    set_setting(team, "seats", 3)

    assert get_settings(team) == {"seats": 3, "support_email": "help@acme.test"}
    assert explain_setting(team, "support_email").is_inherited is True


def test_a_value_the_question_refuses_is_not_written(schema, team):
    with pytest.raises(SettingsValidationError) as error:
        set_setting(team, "support_email", "not-an-email")

    assert "support_email" in error.value.issues
    assert error.value.as_dict()["support_email"][0]["errorKey"] == "invalid_email"
    assert get_setting(team, "support_email") is None


def test_validation_can_be_skipped_for_a_migration(schema, team):
    set_setting(team, "support_email", "not-an-email", validate=False)

    assert get_setting(team, "support_email") == "not-an-email"


def test_writing_the_same_key_twice_keeps_one_answer(schema, team):
    set_setting(team, "seats", 3)
    set_setting(team, "seats", 4)

    scoped = ScopedSettings.for_instance(team, schema, create=False)
    assert scoped is not None
    assert Answer.objects.filter(response=scoped.response).count() == 1
    assert get_setting(team, "seats") == 4


def test_a_key_no_schema_asks_about_is_refused(schema, team):
    with pytest.raises(UnknownSetting):
        set_setting(team, "nonsense", 1)


def test_a_key_two_schemas_ask_about_has_to_be_disambiguated(schema, make_settings_schema, team):
    make_settings_schema("billing", ["seats"])

    with pytest.raises(AmbiguousSetting):
        set_setting(team, "seats", 3)

    set_setting(team, "seats", 3, schema="workspace")
    assert get_setting(team, "seats", schema="workspace") == 3
    assert get_setting(team, "seats", schema="billing") is None


def test_a_level_the_schema_is_not_held_at_is_refused(
    make_settings_schema, levels, organization, team
):
    make_settings_schema("policy", ["retention_days"], levels=[levels["organization"]])

    set_setting(organization, "retention_days", 30)
    with pytest.raises(LevelNotAllowed):
        set_setting(team, "retention_days", 7)

    assert get_setting(team, "retention_days") == 30


def test_the_global_level_is_written_with_no_holder(schema, team):
    set_setting(None, "seats", 5)

    assert get_setting(None, "seats") == 5
    assert get_setting(team, "seats") == 5


def test_unsetting_something_that_was_never_set_says_so(schema, team):
    assert unset_setting(team, "seats") is False


def test_values_are_stored_under_one_row_per_object_and_schema(schema, team):
    set_settings(team, {"seats": 3, "support_email": "help@platform.test"})

    assert ScopedSettings.objects.filter(schema=schema, object_id=str(team.pk)).count() == 1
