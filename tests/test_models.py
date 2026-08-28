"""What the storage models will not let a caller record."""

from __future__ import annotations

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from vinta_django_questionnaires.models import Questionnaire, QuestionnaireResponse

from tests.testapp.models import Organization, Team
from vinta_django_cascading_settings.exceptions import SettingsConfigurationError
from vinta_django_cascading_settings.expressions import SettingValue
from vinta_django_cascading_settings.models import ScopedSettings, SettingsSchema

pytestmark = pytest.mark.django_db


def test_the_global_level_holds_no_object(schema, levels, team):
    scoped = ScopedSettings(
        schema=schema,
        level=levels["global"],
        content_type=ContentType.objects.get_for_model(Team),
        object_id=str(team.pk),
        response=QuestionnaireResponse.objects.create(questionnaire_version=schema.version),
    )

    with pytest.raises(ValidationError) as error:
        scoped.full_clean()

    assert "content_type" in error.value.message_dict


def test_a_level_will_not_hold_another_model(schema, levels, organization):
    scoped = ScopedSettings(
        schema=schema,
        level=levels["team"],
        content_type=ContentType.objects.get_for_model(Organization),
        object_id=str(organization.pk),
        response=QuestionnaireResponse.objects.create(questionnaire_version=schema.version),
    )

    with pytest.raises(ValidationError) as error:
        scoped.full_clean()

    assert "content_type" in error.value.message_dict


def test_an_object_level_says_which_object(schema, levels):
    scoped = ScopedSettings(
        schema=schema,
        level=levels["team"],
        content_type=ContentType.objects.get_for_model(Team),
        object_id="",
        response=QuestionnaireResponse.objects.create(questionnaire_version=schema.version),
    )

    with pytest.raises(ValidationError) as error:
        scoped.full_clean()

    assert "object_id" in error.value.message_dict


def test_a_response_to_another_questionnaire_is_refused(schema, levels, team, workspace_version):
    other = Questionnaire.objects.create(key="other", name="Other")
    version = other.versions.create(version=1, title="Other")
    scoped = ScopedSettings(
        schema=schema,
        level=levels["team"],
        content_type=ContentType.objects.get_for_model(Team),
        object_id=str(team.pk),
        response=QuestionnaireResponse.objects.create(questionnaire_version=version),
    )

    with pytest.raises(ValidationError) as error:
        scoped.full_clean()

    assert "response" in error.value.message_dict


def test_a_schema_whose_questionnaire_has_no_version_says_so(db, levels):
    questionnaire = Questionnaire.objects.create(key="empty", name="Empty")
    schema = SettingsSchema.objects.create(key="empty", questionnaire=questionnaire)

    with pytest.raises(SettingsConfigurationError):
        schema.version  # noqa: B018 -- reading it is what raises


def test_a_schema_cannot_be_active_while_its_questionnaire_is_not(db, workspace_version):
    questionnaire = workspace_version.questionnaire
    questionnaire.is_active = False
    questionnaire.save()

    with pytest.raises(ValidationError) as error:
        SettingsSchema.objects.create(key="workspace", questionnaire=questionnaire)

    assert "is_active" in error.value.message_dict


def test_a_schema_with_no_levels_named_is_held_anywhere(schema, levels):
    assert schema.allows(levels["team"]) is True
    assert schema.allows(levels["global"]) is True


def test_a_settings_expression_needs_a_queryset_to_resolve_against(levels):
    with pytest.raises(TypeError):
        SettingValue("seats").resolve_expression()


def test_looking_for_values_that_were_never_recorded_makes_nothing(schema, team):
    assert ScopedSettings.for_instance(team, schema, create=False) is None
    assert ScopedSettings.objects.count() == 0
