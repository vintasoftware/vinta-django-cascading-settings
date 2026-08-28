"""A small JSON API for one object's settings.

These views are opt-in: include ``vinta_django_cascading_settings.urls`` where
you want them.  What they hand back is the questionnaire's own validation plan
alongside the resolved values, so a client that can already render a
questionnaire can render a settings form -- with each field showing what the
object would inherit if it set nothing.

Who may read and who may write are methods to override rather than settings,
and the default is the careful one: staff only.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from django.core.exceptions import BadRequest, PermissionDenied
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseBase, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from django.views import View
from vinta_django_questionnaires.plan import questionnaire_plan

from vinta_django_cascading_settings.api import (
    ResolvedSetting,
    explain_settings,
    lock_setting,
    set_settings,
    unlock_setting,
    unset_settings,
)
from vinta_django_cascading_settings.exceptions import (
    CascadingSettingsError,
    LevelNotAllowed,
    SettingLocked,
    SettingsValidationError,
    UnknownSetting,
)
from vinta_django_cascading_settings.models import SettingsLevel, SettingsSchema

if TYPE_CHECKING:
    from django.db.models import Model
    from django.http import HttpRequest

#: What each problem means over HTTP.
STATUS_CODES: dict[type[CascadingSettingsError], int] = {
    SettingsValidationError: 422,
    SettingLocked: 409,
    LevelNotAllowed: 409,
    UnknownSetting: 400,
}


def status_for(error: CascadingSettingsError) -> int:
    for error_class, status in STATUS_CODES.items():
        if isinstance(error, error_class):
            return status
    return 400


def serialize_setting(resolved: ResolvedSetting) -> dict[str, Any]:
    """One setting, with the account of where its value came from."""
    return {
        "value": resolved.value,
        "isSet": resolved.is_set,
        "isOwn": resolved.is_own,
        "isInherited": resolved.is_inherited,
        "isLocked": resolved.is_locked,
        "source": (
            {
                "level": resolved.level,
                "scope": resolved.scope_key,
                "schema": resolved.schema,
                "objectId": resolved.object_id,
                "depth": resolved.depth,
            }
            if resolved.is_set
            else None
        ),
    }


class SettingsAccessMixin:
    """Who may look at an object's settings, and who may change them."""

    def check_access(
        self, request: HttpRequest, *, schema: SettingsSchema, holder: Model | None
    ) -> None:
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated or not user.is_staff:
            raise PermissionDenied(_("Only staff may read or write settings."))


class ApiView(SettingsAccessMixin, View):
    """JSON in, JSON out, with each problem mapped to a status code."""

    http_method_names = ["get", "patch", "put", "head", "options"]

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        try:
            return super().dispatch(request, *args, **kwargs)
        except PermissionDenied as exc:
            return self.error(str(exc) or str(_("Not allowed.")), status=403)
        except BadRequest as exc:
            return self.error(str(exc), status=400)
        except SettingsValidationError as exc:
            return JsonResponse({"errors": exc.as_dict()}, status=422)
        except CascadingSettingsError as exc:
            return self.error(str(exc), status=status_for(exc))

    def body(self, request: HttpRequest) -> dict[str, Any]:
        if not request.body:
            return {}
        try:
            payload = json.loads(request.body)
        except ValueError as exc:
            raise BadRequest(_("The body is not JSON.")) from exc
        if not isinstance(payload, dict):
            raise BadRequest(_("The body has to be an object."))
        return payload

    def error(self, detail: str, *, status: int) -> HttpResponse:
        return JsonResponse({"detail": detail}, status=status)


class SettingsView(ApiView):
    """One level's settings for one object, read and written.

    ``GET`` hands back the plan and every setting resolved through the chain.
    ``PATCH`` writes only what it is given: ``values`` to set, ``unset`` to
    hand back to the level above, and ``locks`` to stop the levels below.
    """

    def get(
        self,
        request: HttpRequest,
        schema: str,
        level: str = "",
        object_id: str = "",
        scope_key: str | None = None,
    ) -> HttpResponse:
        settings_schema, holder = self.resolve(schema, level, object_id)
        self.check_access(request, schema=settings_schema, holder=holder)
        return JsonResponse(self.payload(settings_schema, holder, level, scope_key))

    def patch(
        self,
        request: HttpRequest,
        schema: str,
        level: str = "",
        object_id: str = "",
        scope_key: str | None = None,
    ) -> HttpResponse:
        settings_schema, holder = self.resolve(schema, level, object_id)
        self.check_access(request, schema=settings_schema, holder=holder)
        payload = self.body(request)
        values = payload.get("values") or {}
        unset = payload.get("unset") or []
        locks = payload.get("locks") or {}
        force = bool(payload.get("force"))

        with transaction.atomic():
            if values:
                set_settings(holder, values, schema=settings_schema, scope=scope_key, force=force)
            if unset:
                unset_settings(holder, *unset, schema=settings_schema, scope=scope_key)
            for key, locked in locks.items():
                if locked:
                    lock_setting(holder, key, schema=settings_schema, scope=scope_key)
                else:
                    unlock_setting(holder, key, schema=settings_schema, scope=scope_key)
        return JsonResponse(self.payload(settings_schema, holder, level, scope_key))

    put = patch

    # -- the pieces --------------------------------------------------------
    def resolve(
        self, schema: str, level: str, object_id: str
    ) -> tuple[SettingsSchema, Model | None]:
        settings_schema = get_object_or_404(SettingsSchema, key=schema, is_active=True)
        if not level or level == "global":
            return settings_schema, None
        settings_level = get_object_or_404(SettingsLevel, key=level)
        model = settings_level.model
        if model is None:
            raise Http404(_("That level holds no objects."))
        return settings_schema, get_object_or_404(model, pk=object_id)

    def payload(
        self,
        schema: SettingsSchema,
        holder: Model | None,
        level: str,
        scope_key: str | None = None,
    ) -> dict[str, Any]:
        resolved = explain_settings(holder, schema=schema.key, scope=scope_key)
        return {
            "schema": schema.key,
            "level": level or "global",
            "scope": scope_key,
            "objectId": str(holder.pk) if holder is not None else None,
            "plan": questionnaire_plan(schema.version),
            "settings": {key: serialize_setting(entry) for key, entry in resolved.items()},
        }


__all__ = ["ApiView", "SettingsAccessMixin", "SettingsView", "serialize_setting", "status_for"]
