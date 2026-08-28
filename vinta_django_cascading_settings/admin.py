"""The admin: the levels, the schemas, and one page for editing values.

Registering is opt-out, the way the questionnaires package does it, because a
project may already have an admin for one of these models or may want a
different base class under all of them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.conf import settings as django_settings
from django.contrib import admin, messages
from django.contrib.admin.utils import unquote
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from vinta_django_cascading_settings.forms import SettingsForm
from vinta_django_cascading_settings.models import (
    ScopedSettings,
    SettingLock,
    SettingsLevel,
    SettingsSchema,
)

if TYPE_CHECKING:
    from django.db.models import Model, QuerySet
    from django.http import HttpRequest, HttpResponse

TEMPLATE = "vinta_django_cascading_settings/admin/settings_form.html"


def schemas_for(level: SettingsLevel | None) -> list[SettingsSchema]:
    """The schemas *level* is allowed to hold, or every active one."""
    active = SettingsSchema.objects.filter(is_active=True)
    if level is None:
        return list(active)
    return [schema for schema in active if schema.allows(level)]


class CascadingSettingsAdminMixin:
    """Adds a settings page to the admin of a model that is a level.

    ``TeamAdmin(CascadingSettingsAdminMixin, admin.ModelAdmin)`` gets a
    ``Settings`` page per team, showing every setting with what it currently
    resolves to and where that came from.  Put ``settings_link`` in
    ``list_display`` for a way in from the changelist.
    """

    #: Which schema to edit when more than one applies. Left empty, the page
    #: offers every schema the level is allowed to hold.
    settings_schema: str | None = None

    def get_urls(self) -> list[Any]:
        opts = self.model._meta  # type: ignore[attr-defined]
        own = [
            path(
                "<path:object_id>/settings/",
                self.admin_site.admin_view(self.settings_view),  # type: ignore[attr-defined]
                name=f"{opts.app_label}_{opts.model_name}_settings",
            )
        ]
        inherited: list[Any] = super().get_urls()  # type: ignore[misc]
        return own + inherited

    def settings_holder(self, obj: Model) -> Model | None:
        """Whose settings the page edits. The object itself, here."""
        return obj

    @admin.display(description=_("Settings"))
    def settings_link(self, obj: Model) -> Any:
        opts = obj._meta
        url = reverse(f"admin:{opts.app_label}_{opts.model_name}_settings", args=[obj.pk])
        return format_html('<a href="{}">{}</a>', url, _("Settings"))

    def settings_view(
        self, request: HttpRequest, object_id: str, extra_context: dict[str, Any] | None = None
    ) -> HttpResponse:
        obj = self.get_object(request, unquote(object_id))  # type: ignore[attr-defined]
        if obj is None:
            raise Http404(_("No object matches this id."))
        if not self.has_change_permission(request, obj):  # type: ignore[attr-defined]
            raise PermissionDenied
        return render_settings_page(
            self,  # type: ignore[arg-type]
            request,
            obj=obj,
            holder=self.settings_holder(obj),
            schema_key=request.GET.get("schema") or self.settings_schema,
        )


def render_settings_page(
    model_admin: admin.ModelAdmin,
    request: HttpRequest,
    *,
    obj: Model,
    holder: Model | None,
    schema_key: str | None = None,
) -> HttpResponse:
    """The settings page itself, shared by every admin that shows one."""
    level = holder_level(holder)
    available = schemas_for(level)
    if not available:
        raise Http404(_("There are no settings to edit here."))
    schema = next((entry for entry in available if entry.key == schema_key), available[0])

    form = SettingsForm(request.POST or None, schema=schema, holder=holder)
    if request.method == "POST" and form.is_valid():
        form.save()
        model_admin.message_user(request, _("Settings saved."), messages.SUCCESS)
        return HttpResponseRedirect(f"{request.path}?schema={schema.key}")

    opts = obj._meta
    context = {
        **model_admin.admin_site.each_context(request),
        "opts": opts,
        "original": obj,
        "object_id": obj.pk,
        "title": _("Settings: %(object)s") % {"object": obj},
        "form": form,
        "rows": form.rows(),
        "schema": schema,
        "schemas": available,
        "level": level,
        "holder": holder,
        "media": model_admin.media + form.media,
    }
    return TemplateResponse(request, TEMPLATE, context)


def holder_level(holder: Model | None) -> SettingsLevel | None:
    from vinta_django_cascading_settings.models import level_for_model

    if holder is None:
        return SettingsLevel.objects.filter(content_type__isnull=True).first()
    return level_for_model(type(holder))


class SettingsLevelAdmin(admin.ModelAdmin):
    list_display = ["key", "content_type", "parent", "parent_lookup", "chain"]
    list_select_related = ["content_type", "parent"]
    search_fields = ["key", "name"]
    fields = ["key", "name", "content_type", "parent", "parent_lookup"]

    @admin.display(description=_("Chain"))
    def chain(self, obj: SettingsLevel) -> str:
        return " -> ".join(level.key for level in obj.ancestors())


class SettingsSchemaAdmin(admin.ModelAdmin):
    list_display = ["key", "questionnaire", "is_active", "levels"]
    list_filter = ["is_active"]
    search_fields = ["key"]
    filter_horizontal = ["levels"]

    @admin.display(description=_("Levels"))
    def levels(self, obj: SettingsSchema) -> str:
        return ", ".join(level.key for level in obj.levels.all()) or str(_("every level"))


class SettingLockInline(admin.TabularInline):
    model = SettingLock
    extra = 0
    fields = ["key", "reason"]


class ScopedSettingsAdmin(CascadingSettingsAdminMixin, admin.ModelAdmin):
    list_display = ["__str__", "schema", "level", "scope_key", "target", "settings_link"]
    list_filter = ["schema", "level"]
    list_select_related = ["schema", "level"]
    readonly_fields = ["response"]
    inlines = [SettingLockInline]

    def settings_holder(self, obj: Model) -> Model | None:
        """The object these values belong to, or nothing for the global level."""
        return getattr(obj, "target", None)

    def get_queryset(self, request: HttpRequest) -> QuerySet[Any]:
        return super().get_queryset(request).prefetch_related("locks")


#: The admin classes, in the order they are registered.
REGISTRY: list[tuple[type[Model], type[admin.ModelAdmin]]] = [
    (SettingsLevel, SettingsLevelAdmin),
    (SettingsSchema, SettingsSchemaAdmin),
    (ScopedSettings, ScopedSettingsAdmin),
]


def register(
    site: admin.AdminSite | None = None,
    *,
    model_admin_base: type[admin.ModelAdmin] | None = None,
    inline_base: type[admin.options.InlineModelAdmin] | None = None,
    force: bool = False,
) -> None:
    """Register everything this package has an admin for.

    Anything already registered is left alone unless *force* says otherwise,
    so an admin of your own for one model needs nothing else.  A themed admin
    styles a form through its base class, which is what the two base arguments
    are for.
    """
    target = site or admin.site
    for model, model_admin in REGISTRY:
        if model in target._registry:
            if not force:
                continue
            target.unregister(model)
        target.register(model, _rebased(model_admin, model_admin_base, inline_base))


def unregister(site: admin.AdminSite | None = None) -> None:
    """Take every one of them back off again."""
    target = site or admin.site
    for model, _model_admin in REGISTRY:
        if model in target._registry:
            target.unregister(model)


def _rebased(
    model_admin: type[admin.ModelAdmin],
    model_admin_base: type[admin.ModelAdmin] | None,
    inline_base: type[admin.options.InlineModelAdmin] | None,
) -> type[admin.ModelAdmin]:
    """The same admin, over the bases a themed admin needs underneath it."""
    if model_admin_base is None and inline_base is None:
        return model_admin
    attrs: dict[str, Any] = {}
    if inline_base is not None and model_admin.inlines:
        attrs["inlines"] = [
            type(inline.__name__, (inline, inline_base), {}) for inline in model_admin.inlines
        ]
    bases: tuple[type, ...] = (
        (model_admin, model_admin_base) if model_admin_base is not None else (model_admin,)
    )
    return type(model_admin.__name__, bases, attrs)


if getattr(django_settings, "CASCADING_SETTINGS_REGISTER_ADMIN", True):
    register()


__all__ = [
    "REGISTRY",
    "CascadingSettingsAdminMixin",
    "ScopedSettingsAdmin",
    "SettingsLevelAdmin",
    "SettingsSchemaAdmin",
    "register",
    "render_settings_page",
    "unregister",
]
