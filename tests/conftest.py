"""Shared fixtures: a settings questionnaire, four levels, and a hierarchy."""

from __future__ import annotations

import pytest
from django.contrib.contenttypes.models import ContentType
from vinta_django_questionnaires.models import (
    Page,
    Question,
    QuestionChoice,
    Questionnaire,
    QuestionnaireVersion,
    QuestionValidator,
    Section,
)
from vinta_django_questionnaires.question_types import QuestionType

from tests.testapp.models import Gadget, Member, Organization, Team
from vinta_django_cascading_settings.models import SettingsLevel, SettingsSchema


@pytest.fixture
def workspace_version(db):
    """A questionnaire whose questions are the settings of a workspace."""
    questionnaire = Questionnaire.objects.create(key="workspace", name="Workspace settings")
    version = QuestionnaireVersion.objects.create(
        questionnaire=questionnaire, version=1, title="Workspace settings"
    )
    page = Page.objects.create(questionnaire_version=version, key="general", title="General")
    section = Section.objects.create(page=page, key="general", title="General")
    support_email = Question.objects.create(
        section=section,
        key="support_email",
        title="Support email",
        question_type=QuestionType.FREE_TEXT,
        order=0,
    )
    QuestionValidator.objects.create(question=support_email, validator="email", order=0)
    seats = Question.objects.create(
        section=section,
        key="seats",
        title="Seats",
        question_type=QuestionType.NUMBER,
        order=1,
    )
    # A seat is a whole one, and saying so is what makes it read back as an int.
    QuestionValidator.objects.create(question=seats, validator="integer", order=0)
    Question.objects.create(
        section=section,
        key="sampling_rate",
        title="Sampling rate",
        question_type=QuestionType.NUMBER,
        order=3,
    )
    Question.objects.create(
        section=section,
        key="renews_on",
        title="Renews on",
        question_type=QuestionType.DATE,
        order=4,
    )
    features = Question.objects.create(
        section=section,
        key="features",
        title="Features",
        question_type=QuestionType.MULTIPLE_CHOICE,
        order=2,
    )
    for order, value in enumerate(["exports", "sso", "audit_log"]):
        QuestionChoice.objects.create(
            question=features, value=value, label=value.title(), order=order
        )
    version.publish()
    return version


@pytest.fixture
def levels(db):
    """The global level, then organization, team and member beneath it."""
    root = SettingsLevel.objects.create(key="global", name="Global")
    organization = SettingsLevel.objects.create(
        key="organization",
        content_type=ContentType.objects.get_for_model(Organization),
        parent=root,
    )
    team = SettingsLevel.objects.create(
        key="team",
        content_type=ContentType.objects.get_for_model(Team),
        parent=organization,
        parent_lookup="organization",
    )
    member = SettingsLevel.objects.create(
        key="member",
        content_type=ContentType.objects.get_for_model(Member),
        parent=team,
        parent_lookup="team",
    )
    return {"global": root, "organization": organization, "team": team, "member": member}


@pytest.fixture
def schema(workspace_version, levels):
    return SettingsSchema.objects.create(
        key="workspace", questionnaire=workspace_version.questionnaire
    )


@pytest.fixture
def hierarchy(db):
    organization = Organization.objects.create(name="Acme")
    team = Team.objects.create(organization=organization, name="Platform")
    member = Member.objects.create(team=team, name="Ada")
    return {"organization": organization, "team": team, "member": member}


@pytest.fixture
def organization(hierarchy):
    return hierarchy["organization"]


@pytest.fixture
def team(hierarchy):
    return hierarchy["team"]


@pytest.fixture
def member(hierarchy):
    return hierarchy["member"]


@pytest.fixture
def gadget(db):
    return Gadget.objects.create(name="Widget")


@pytest.fixture
def make_settings_schema(db):
    """A factory for extra schemas, so tests can make keys collide on purpose."""

    def factory(key, keys, *, levels=None, question_type=QuestionType.NUMBER):
        questionnaire = Questionnaire.objects.create(key=key, name=key)
        version = QuestionnaireVersion.objects.create(
            questionnaire=questionnaire, version=1, title=key
        )
        page = Page.objects.create(questionnaire_version=version, key="general", title="General")
        section = Section.objects.create(page=page, key="general", title="General")
        for order, question_key in enumerate(keys):
            Question.objects.create(
                section=section,
                key=question_key,
                title=question_key,
                question_type=question_type,
                order=order,
            )
        version.publish()
        schema = SettingsSchema.objects.create(key=key, questionnaire=questionnaire)
        if levels is not None:
            schema.levels.set(levels)
        return schema

    return factory


@pytest.fixture
def staff_user(db, django_user_model):
    return django_user_model.objects.create_user(
        username="staff", password="settings", is_staff=True
    )


@pytest.fixture
def staff_client(client, staff_user):
    client.force_login(staff_user)
    return client
