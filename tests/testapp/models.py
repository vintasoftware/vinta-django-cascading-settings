"""Models for the test-only app: a three-level hierarchy to cascade through.

An organization holds teams, a team holds members, and each of the three is a
settings level, with the global level above all of them.
"""

from __future__ import annotations

import uuid

from django.db import models

from vinta_django_cascading_settings.expressions import CascadingSettingsQuerySetMixin


class Organization(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.name


class TeamQuerySet(CascadingSettingsQuerySetMixin, models.QuerySet["Team"]):
    pass


class Team(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="teams")
    name = models.CharField(max_length=100)

    objects = TeamQuerySet.as_manager()

    def __str__(self) -> str:
        return self.name


class Member(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="members")
    name = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.name


class Gadget(models.Model):
    """A model that is not a level, so asking it for settings is an error."""

    name = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.name


class Device(models.Model):
    """A level whose primary key is a UUID, which stores differently per backend."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="devices")
    name = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.name
