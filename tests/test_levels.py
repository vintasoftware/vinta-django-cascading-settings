"""How the levels are configured, and what the configuration will not accept."""

from __future__ import annotations

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from tests.testapp.models import Gadget, Member, Organization, Team
from vinta_django_cascading_settings.chain import build_chain
from vinta_django_cascading_settings.exceptions import SettingsConfigurationError
from vinta_django_cascading_settings.models import SettingsLevel

pytestmark = pytest.mark.django_db


def test_the_chain_goes_all_the_way_up_to_the_global_level(levels):
    chain = build_chain(Member)

    assert [(link.level.key, link.depth, link.lookup) for link in chain] == [
        ("member", 0, ""),
        ("team", 1, "team"),
        ("organization", 2, "team__organization"),
        ("global", 3, None),
    ]


def test_a_level_reaches_its_parent_by_the_path_it_is_given(levels):
    assert [link.pk_path for link in build_chain(Member)[:3]] == [
        "pk",
        "team__pk",
        "team__organization__pk",
    ]


def test_a_model_with_no_level_has_no_chain(levels):
    with pytest.raises(SettingsConfigurationError):
        build_chain(Gadget)


def test_a_path_that_is_not_a_field_is_refused(levels):
    with pytest.raises(ValidationError) as error:
        SettingsLevel.objects.create(
            key="gadget",
            content_type=ContentType.objects.get_for_model(Gadget),
            parent=levels["organization"],
            parent_lookup="nonsense",
        )

    assert "parent_lookup" in error.value.message_dict


def test_a_path_that_can_yield_several_rows_is_refused(levels):
    """An organization has many teams, so "teams" names no single parent."""
    scope = SettingsLevel(
        key="upside_down",
        content_type=ContentType.objects.get_for_model(Organization),
        parent=levels["team"],
        parent_lookup="teams",
    )

    with pytest.raises(ValidationError) as error:
        scope.full_clean()

    assert "single-valued" in str(error.value.message_dict["parent_lookup"])


def test_a_path_that_lands_on_the_wrong_model_is_refused(levels):
    scope = SettingsLevel(
        key="member_of_an_organization",
        content_type=ContentType.objects.get_for_model(Member),
        parent=levels["organization"],
        parent_lookup="team",
    )

    with pytest.raises(ValidationError) as error:
        scope.full_clean()

    assert "parent_lookup" in error.value.message_dict


def test_a_level_under_a_real_parent_has_to_say_how_to_reach_it(levels):
    scope = SettingsLevel(
        key="loose",
        content_type=ContentType.objects.get_for_model(Gadget),
        parent=levels["organization"],
    )

    with pytest.raises(ValidationError) as error:
        scope.full_clean()

    assert "parent_lookup" in error.value.message_dict


def test_the_global_level_has_nothing_above_it(levels):
    levels["global"].parent = levels["organization"]

    with pytest.raises(ValidationError) as error:
        levels["global"].full_clean()

    assert "parent" in error.value.message_dict


def test_there_is_only_one_global_level(levels):
    with pytest.raises(ValidationError):
        SettingsLevel.objects.create(key="also_global")


def test_a_model_is_a_level_only_once(levels):
    with pytest.raises(ValidationError):
        SettingsLevel.objects.create(
            key="team_again",
            content_type=ContentType.objects.get_for_model(Team),
            parent=levels["organization"],
            parent_lookup="organization",
        )


def test_a_level_cannot_inherit_from_itself(levels):
    levels["team"].parent = levels["team"]

    with pytest.raises(ValidationError) as error:
        levels["team"].full_clean()

    assert "parent" in error.value.message_dict


def test_a_loop_in_the_levels_is_reported_rather_than_walked(levels):
    levels["organization"].parent = levels["member"]
    levels["organization"].parent_lookup = "teams"
    levels["organization"].save(validate=False)

    with pytest.raises(SettingsConfigurationError):
        build_chain(Team)
