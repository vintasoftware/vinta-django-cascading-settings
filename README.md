# Vinta Django Cascading Settings

A reusable Django application for managing settings in multiple levels with inheritance

[![PyPI](https://img.shields.io/pypi/v/vinta-django-cascading-settings.svg)](https://pypi.org/project/vinta-django-cascading-settings/)
[![CI](https://github.com/vintasoftware/vinta-django-cascading-settings/actions/workflows/ci.yml/badge.svg)](https://github.com/vintasoftware/vinta-django-cascading-settings/actions/workflows/ci.yml)

Supports Python 3.10, 3.11, 3.12, 3.13, 3.14 and Django 5.2, 6.0, on PostgreSQL
and SQLite.


## Installation

```bash
pip install vinta-django-cascading-settings
```

Then add the app to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    ...,
    "vinta_django_cascading_settings",
]
```


## Usage

Settings are held at several levels -- a global one, an organization, a team, a
member -- and reading one means asking the object in front of you and, failing
that, everything above it.  This package does that in **one SQL expression**, so
a resolved setting is something you can annotate, filter, order and join on
rather than something you compute after the query comes back.

Two other packages do the parts they already do: Django's content type framework
says which model is a level and which level it inherits from, and
[vinta-django-questionnaires](https://github.com/vintasoftware/vinta-django-questionnaires)
says what the settings *are* -- their keys, their types, their validation, and
the plan a dynamic form is rendered from.

### Defining the levels

A level is a `SettingsLevel`: a content type, the level above it, and the ORM
path that gets from one to the other.

```python
from django.contrib.contenttypes.models import ContentType
from vinta_django_cascading_settings.models import SettingsLevel

everything = SettingsLevel.objects.create(key="global")
organization = SettingsLevel.objects.create(
    key="organization",
    content_type=ContentType.objects.get_for_model(Organization),
    parent=everything,
)
team = SettingsLevel.objects.create(
    key="team",
    content_type=ContentType.objects.get_for_model(Team),
    parent=organization,
    parent_lookup="organization",
)
```

`parent_lookup` is an ORM path, not an attribute name, and every hop has to be a
foreign key or a one-to-one -- `"organization"`, or `"team__organization"` to
skip a level.  That is what the resolver follows in SQL, so a path that can
yield several rows, or one that only Python knows how to walk, is refused when
the level is saved.  The level with no content type is the global one, and every
chain ends there.

### Defining the settings

A `SettingsSchema` points at a questionnaire.  Its question keys are the setting
keys, its question types say what a value looks like, and its validator chains
are what a value has to pass:

```python
from vinta_django_questionnaires.models import (
    Page,
    Question,
    Questionnaire,
    QuestionnaireVersion,
    Section,
)
from vinta_django_questionnaires.question_types import QuestionType
from vinta_django_cascading_settings.models import SettingsSchema

questionnaire = Questionnaire.objects.create(key="workspace", name="Workspace settings")
version = QuestionnaireVersion.objects.create(
    questionnaire=questionnaire, version=1, title="Workspace"
)
page = Page.objects.create(questionnaire_version=version, key="general", title="General")
section = Section.objects.create(page=page, key="general", title="General")
Question.objects.create(
    section=section,
    key="support_email",
    title="Support email",
    question_type=QuestionType.FREE_TEXT,
)
version.publish()

SettingsSchema.objects.create(key="workspace", questionnaire=questionnaire)
```

Everything the questionnaires package can do to a definition applies here:
conditions, value sets, widgets, forking a version rather than editing one that
is in use.  A schema can be pinned to the levels allowed to hold it with
`schema.levels.set([...])`; left empty, every level may.

### Reading a setting

```python
from vinta_django_cascading_settings import get_setting, get_settings, explain_setting

get_setting(team, "support_email")  # the value, resolved through the chain
get_setting(team, "seats", default=5)  # ... or the default, if no level set it
get_settings(team)  # every key that is set, as a dict
get_setting(None, "support_email")  # the global level on its own
```

`explain_setting` says where a value came from, which is what a UI needs to show
"inherited from Acme" next to a field:

```python
resolved = explain_setting(team, "support_email")
resolved.value  # "help@acme.test"
resolved.level  # "organization"
resolved.depth  # 1 -- one level up
resolved.is_inherited  # True
resolved.is_own  # False
resolved.is_locked  # False
```

A level that set a value to `None` has set it: `get_setting` returns `None`
rather than the default, and the levels above are not consulted.  Only a key
with no answer anywhere is unset.

### Resolving in the database

`get_setting` is a thin wrapper over an expression, and the expression is the
point.  Nothing is merged in Python, so a setting behaves like a column:

```python
from vinta_django_cascading_settings import SettingValue, annotate_settings

Team.objects.annotate(seats=SettingValue("seats")).filter(seats=10)

annotate_settings(
    Team.objects.all(), "seats", "support_email"
)  # setting_seats, setting_support_email
annotate_settings(Team.objects.all(), "seats", sources=True)  # ... and setting_seats_source
```

Add the mixin to a queryset for a shorter spelling:

```python
from vinta_django_cascading_settings import CascadingSettingsQuerySetMixin


class TeamQuerySet(CascadingSettingsQuerySetMixin, models.QuerySet):
    pass


Team.objects.with_settings("seats").order_by("setting_seats")
```

One correlated subquery resolves the whole chain: it looks at the values held
anywhere along it, orders them so the winner is first, and takes one row.  Every
level's identity comes from the outer row, so annotating a thousand teams is
still one query.  Reading the configuration -- which levels there are, and how
each reaches the next -- is what builds the expression, and it happens once per
annotation rather than once per row.

### What a setting comes back as

A value is stored as JSON, and JSON compares as JSON: `100` sorts before `9`,
and `>` means nothing.  So the subquery reads the scalar out of the JSON and
casts it -- in SQL, in the same query -- to the type the question says it is.
Nothing has to be passed for that: a number annotates as a number.

```python
from django.db.models import Sum

teams = Team.objects.with_settings("seats")
teams.filter(setting_seats__gt=10)
teams.order_by("setting_seats")
teams.aggregate(Sum("setting_seats"))

get_setting(team, "seats")  # 10, an int
get_setting(team, "renews_on")  # datetime.date(2026, 9, 30)
```

| Question type | Read as |
| --- | --- |
| `number`, `time_duration` | float, or **int** when the question declares the `integer` validator |
| `year` | int |
| `date`, `date_time`, `time` | `date`, `datetime`, `time` |
| `free_text`, `url`, `single_choice`, `single_select`, `month` | str |
| everything else | JSON, as stored |

Whether a number is a whole one is the one thing the type alone cannot say, so
it is read from the question's own validator chain -- a `number` that declares
`integer` is an integer, and every other number is a float.

Anything that is not a scalar -- a multiple choice, a range, a matrix, a nested
answer set -- stays JSON, and so does a key two schemas disagree about, because
one cast cannot be right for both.  A JSON value is compared as JSON, which
Django adapts for you: `filter(setting_features=["exports"])` works.

The cast is portable: PostgreSQL will not cast `jsonb` to a number at all, so
the scalar comes out through `#>> '{}'` there, `JSON_EXTRACT` on SQLite,
`JSON_UNQUOTE(JSON_EXTRACT(...))` on MySQL and `JSON_VALUE` on Oracle, and the
cast follows.  To override the lot, pass an `output_field`:

```python
from django.db.models import TextField

Team.objects.annotate(seats=SettingValue("seats", output_field=TextField()))
```

### Writing, and taking it back

```python
from vinta_django_cascading_settings import set_setting, set_settings, unset_setting

set_setting(team, "seats", 3)  # this level, this key
set_settings(team, {"seats": 3, "support_email": "help@platform.test"})
set_setting(None, "seats", 5)  # the global level
unset_setting(team, "seats")  # inherited again
```

Only the keys named are written.  A level that overrides one setting does not
quietly take ownership of the rest, which is what keeps the cascade meaningful
-- and it is why values are written directly rather than through the
questionnaire's page-at-a-time submission, which records a whole page at once.

Each value goes through its question's validator chain, and a value that does
not hold up raises `SettingsValidationError` with the issues keyed by setting:

```python
set_setting(team, "support_email", "not-an-email")
# SettingsValidationError: {"support_email": [invalid_email]}
```

Pass `validate=False` from a data migration that knows better.

### Locking

A level can stop the levels below it from having their way:

```python
set_setting(organization, "seats", 10, locked=True)

get_setting(team, "seats")  # 10, whatever the team says
set_setting(team, "seats", 3)  # SettingLocked
```

A lock beats every value beneath the level that set it, and when two levels lock
the same key the outermost one wins -- a lock is set to constrain what is under
it, so the constraint furthest out is the one that holds.  `force=True` writes
under a lock anyway, for a caller that means it; the value is recorded and stays
unread until the lock is lifted.

### Tenants

The questionnaires package makes a questionnaire and a response belong to a
scope -- a tenant, a workspace, or the installation at large -- and settings
inherit that boundary with one rule of their own on top of it:

> **The global level is the installation's. Every other level is a tenant's.**

Defaults that apply to everyone are what the global level is for, so it holds
exactly one set of values per schema, in the global scope, and every tenant
reads them. Everything below it belongs to one tenant and is read by that
tenant alone. A tenant that wants its own answer sets it at a level it owns.

Nothing has to be configured for that: an installation that never points
`QUESTIONNAIRES_SCOPE_MODEL` anywhere has one scope, everything lands in it,
and the boundary separates nothing. An installation that does say which tenant
it is reading:

```python
get_setting(team, "seats", scope=acme)  # a scope, a scope key, or the tenant itself
set_setting(team, "seats", 10, scope=acme)
Team.objects.with_settings("seats", scope=acme)
```

The scope goes into the same subquery as everything else: the levels below the
global one are matched on the tenant as well as on the object, while the global
level is matched on neither, which is what makes its defaults everyone's. Values
carry the tenant that set them, so `explain_setting(...).scope_key` says whose
they are, and a holder that already belongs to one tenant will not take values
from another.

Where a tenant comes from is the project's business. The API views read it from
the URL, so mounting them under a prefix that captures a `scope_key` is enough:

```python
path("api/<str:scope_key>/settings/", include("vinta_django_cascading_settings.urls"))
```

### The admin

The levels, the schemas and the stored values are registered when the app is
installed, and there is a settings page for any model that is a level:

```python
from vinta_django_cascading_settings.admin import CascadingSettingsAdminMixin


@admin.register(Team)
class TeamAdmin(CascadingSettingsAdminMixin, admin.ModelAdmin):
    list_display = ["name", "settings_link"]
```

The page has one box per setting, showing what this level set and, underneath,
what the setting would be inherited as and from where.  Boxes hold JSON, because
a box has to be able to say three different things: a value, nothing at all --
which means inherit -- and `null`, which means nothing on purpose.  An empty box
is the second; `null` typed into it is the third.

Registering is opt-out, the way the questionnaires package does it:

```python
CASCADING_SETTINGS_REGISTER_ADMIN = False
```

```python
from vinta_django_cascading_settings.admin import register, unregister

register()  # everything not already registered
register(model_admin_base=ModelAdmin, inline_base=TabularInline)  # under a theme's bases
register(force=True)
unregister()
```

### The HTTP API

Include the views where you want them:

```python
urlpatterns = [path("api/settings/", include("vinta_django_cascading_settings.urls"))]
```

Mount them under a prefix that captures a `scope_key` and every view below reads
that tenant, the way the questionnaires package does it:

```python
path("api/<str:scope_key>/settings/", include("vinta_django_cascading_settings.urls"))
```

| Endpoint | What it does |
| --- | --- |
| `GET` `{schema}/{level}/{id}/` | The plan, and every setting with where its value came from |
| `PATCH` `{schema}/{level}/{id}/` | Set, unset and lock, in one call |
| `GET` `PATCH` `{schema}/global/` | The same, for the global level |

A `GET` hands back the questionnaire's own validation plan alongside the values,
so a client that can already render a questionnaire can render a settings form,
with each field showing what it would inherit if it set nothing:

```json
{
  "schema": "workspace",
  "level": "team",
  "scope": "acme",
  "objectId": "12",
  "plan": {"planVersion": 1, "pages": []},
  "settings": {
    "seats": {
      "value": 10,
      "isSet": true,
      "isOwn": false,
      "isInherited": true,
      "isLocked": false,
      "source": {
        "level": "organization",
        "scope": "acme",
        "schema": "workspace",
        "objectId": "3",
        "depth": 1
      }
    }
  }
}
```

A `PATCH` writes only what it is given:

```json
{"values": {"seats": 3}, "unset": ["support_email"], "locks": {"seats": true}}
```

A value the question refuses comes back as `422` with the issues keyed by
setting; a key a level above has locked comes back as `409`.  Who may read and
who may write are methods on `SettingsAccessMixin` rather than settings, and the
default is the careful one: staff only.

### Things worth knowing

- **Setting keys are question keys.** If two schemas ask the same key, pass
  `schema="..."` to say which one you mean; otherwise the lookup raises
  `AmbiguousSetting`.
- **A holder's primary key is stored as the database writes it**, so the column
  and the query's own `CAST` agree on every backend -- integer, UUID or
  otherwise.  Moving that table between backends is the one case where they
  could disagree.
- **A level is a content type**, so a proxy model resolves as its concrete one.
- **A tenant is a questionnaire scope**, the swappable model 0.2.0 of the
  questionnaires package introduced. Settings add one rule to it: the global
  level is the installation's and everything below it is a tenant's.
- **PostgreSQL and SQLite are what the suite runs on**, and the two disagree
  about enough of this to be worth saying: SQLite will not resolve an outer
  column in a subquery's `ORDER BY`, and PostgreSQL will not cast `jsonb` to
  anything but text. Both are handled. The MySQL and Oracle spellings of the
  JSON scalar are there, and the suite does not exercise them.
- **Values live in questionnaire answers**, under one `ScopedSettings` row per
  object and schema.  Everything the questionnaires package knows how to do with
  a response -- reporting, exporting, the acknowledgement trail on the
  definition -- applies to them.


## Development

The project uses [uv](https://docs.astral.sh/uv/) for dependency management and
[tox](https://tox.wiki/) to run the suite across the support matrix.

```bash
uv sync --all-groups
uv run pre-commit install --install-hooks --hook-type commit-msg
uv run pytest
```

The suite runs on SQLite by default. To run it against PostgreSQL, point it at a
server and say so:

```bash
docker run -d --rm --name settings-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=cascading_settings -p 5432:5432 postgres:17-alpine
```

```bash
TEST_DATABASE=postgres uv run pytest
```

`PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD` and `PGDATABASE` override the
defaults, which are the ones above. Any tox environment takes a `-pg` factor to
the same end -- `uv run tox -e py313-dj52-pg` -- and CI runs the oldest supported
Django against PostgreSQL 14 and the newest against 17.

Useful commands:

| Command | What it does |
| --- | --- |
| `uv run pytest` | Run the test suite on the current interpreter |
| `TEST_DATABASE=postgres uv run pytest` | Run it against PostgreSQL instead of SQLite |
| `uv run tox` | Run it on every supported Python and Django |
| `uv run tox -e lint` | Check formatting and lint rules |
| `uv run tox -e types` | Type check with mypy and django-stubs |
| `uv run tox -e build` | Build the sdist and wheel and check the metadata |
| `uv run python -m tests.manage makemigrations` | Generate migrations for the app |

## Releasing

1. Bump the version in `pyproject.toml` and move the `Unreleased` section of
   `CHANGELOG.md` under the new number.
2. Tag the commit as `vX.Y.Z` and publish a GitHub release.
3. The `publish.yml` workflow builds, verifies that the tag matches the version,
   uploads to PyPI through trusted publishing, and attaches Sigstore signatures.

To rehearse a release, run the workflow manually with the `testpypi` target.

## Staying up to date with the template

This project was generated from
[vinta-django-package](https://github.com/vintasoftware/vinta-django-package).
To pull in later improvements to the tooling:

```bash
uvx copier update --trust
```


## License

MIT. See [LICENSE](LICENSE).
