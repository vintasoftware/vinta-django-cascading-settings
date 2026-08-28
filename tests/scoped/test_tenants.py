"""Settings under a real tenant boundary.

The rule these pin down: the global level holds the installation's defaults and
every tenant reads them, and every level below it belongs to one tenant and is
read by that tenant alone.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from tests.testapp.models import Team
from vinta_django_cascading_settings import (
    annotate_settings,
    explain_setting,
    get_setting,
    set_setting,
)
from vinta_django_cascading_settings.models import ScopedSettings

pytestmark = pytest.mark.django_db


def test_the_global_level_is_read_by_every_tenant(shared_schema, tenants):
    set_setting(None, "support_email", "help@installation.test")

    for tenant in tenants.values():
        team = tenant["team"]
        scope = tenant["scope"]
        assert get_setting(team, "support_email", scope=scope) == "help@installation.test"


def test_each_tenant_sets_the_same_key_at_its_own_level(shared_schema, tenants):
    acme, globex = tenants["acme"], tenants["globex"]

    set_setting(acme["organization"], "seats", 10, scope=acme["scope"])
    set_setting(globex["organization"], "seats", 99, scope=globex["scope"])

    assert get_setting(acme["team"], "seats", scope=acme["scope"]) == 10
    assert get_setting(globex["team"], "seats", scope=globex["scope"]) == 99


def test_a_tenant_reads_nothing_of_another_tenants(shared_schema, tenants):
    acme, globex = tenants["acme"], tenants["globex"]
    set_setting(acme["organization"], "seats", 10, scope=acme["scope"])

    # Acme's own team, read as though it were Globex's: the values are Acme's,
    # so under Globex's scope there is nothing to see.
    assert get_setting(acme["team"], "seats", scope=globex["scope"]) is None
    assert get_setting(acme["team"], "seats", scope=acme["scope"]) == 10


def test_a_tenant_still_falls_back_to_the_installation_defaults(shared_schema, tenants):
    acme, globex = tenants["acme"], tenants["globex"]
    set_setting(None, "seats", 3)
    set_setting(acme["organization"], "seats", 10, scope=acme["scope"])

    assert get_setting(acme["team"], "seats", scope=acme["scope"]) == 10
    assert get_setting(globex["team"], "seats", scope=globex["scope"]) == 3


def test_values_carry_the_tenant_that_set_them(shared_schema, tenants):
    acme = tenants["acme"]
    set_setting(acme["organization"], "seats", 10, scope=acme["scope"])

    scoped = ScopedSettings.objects.get(object_id=str(acme["organization"].pk))
    assert scoped.scope_key == acme["scope"].scope_key
    assert scoped.response.scope_key == acme["scope"].scope_key

    resolved = explain_setting(acme["team"], "seats", scope=acme["scope"])
    assert resolved.scope_key == acme["scope"].scope_key
    assert resolved.level == "organization"


def test_the_installation_defaults_belong_to_no_tenant(shared_schema, tenants):
    set_setting(None, "seats", 3)

    scoped = ScopedSettings.objects.get(content_type__isnull=True)
    assert scoped.scope_key == ""
    assert explain_setting(None, "seats").scope_key == ""


def test_the_global_level_refuses_to_belong_to_a_tenant(shared_schema, tenants, levels):
    """A tenant that wants its own answer sets it at a level it owns."""
    acme = tenants["acme"]
    scoped = ScopedSettings.for_global(shared_schema)
    assert scoped is not None
    scoped.response.scope = acme["scope"]
    scoped.response.scope_key = acme["scope"].scope_key
    scoped.scope_key = acme["scope"].scope_key

    with pytest.raises(ValidationError) as error:
        scoped.full_clean()

    assert "response" in error.value.message_dict


def test_writing_a_holder_that_is_already_another_tenants_is_refused(shared_schema, tenants):
    acme, globex = tenants["acme"], tenants["globex"]
    set_setting(acme["team"], "seats", 4, scope=acme["scope"])

    from vinta_django_cascading_settings import LevelNotAllowed

    with pytest.raises(LevelNotAllowed):
        set_setting(acme["team"], "seats", 5, scope=globex["scope"])


def test_annotating_a_queryset_stays_inside_one_tenant(shared_schema, tenants):
    acme, globex = tenants["acme"], tenants["globex"]
    set_setting(None, "seats", 1)
    set_setting(acme["organization"], "seats", 10, scope=acme["scope"])
    set_setting(globex["organization"], "seats", 99, scope=globex["scope"])

    rows = annotate_settings(Team.objects.order_by("name"), "seats", scope=acme["scope"])

    # Acme's team reads Acme's value; Globex's reads the installation default,
    # because Globex's own value is not Acme's to see.
    assert [row.setting_seats for row in rows] == [10, 1]


def test_a_single_tenant_read_still_works_without_saying_which(shared_schema, tenants):
    acme = tenants["acme"]
    set_setting(acme["organization"], "seats", 10, scope=acme["scope"])

    assert get_setting(acme["team"], "seats") == 10
