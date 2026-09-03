# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [Unreleased]

### Changed

- The `vinta-django-questionnaires` pin widens to `<0.4.0`. 0.3.0 adds i18n --
  a `strings` prop on the React editor and a `locale/` catalog for the Django
  app -- and touches no Python source this package imports from: `models.py`,
  `question_types.py`, `validators/base.py`, `submissions.py`, `plan.py` and
  `models_registry.py` are byte-identical to 0.2.3's.


## [0.1.0] - 2026-08-27

### Added

- `SettingsLevel`: the levels settings cascade through, tied to models by content
  type, each naming the ORM path to the level above it. Called a level rather
  than a scope because 0.2.0 of the questionnaires package took that word for
  the tenant boundary, and a package cannot mean two things by it.
- `SettingsSchema`: a questionnaire read as a set of settings, so the keys,
  types, validation and render plan come from
  [vinta-django-questionnaires](https://github.com/vintasoftware/vinta-django-questionnaires).
- `ScopedSettings` and `SettingLock`: what one object has set, held as
  questionnaire answers, and the values the levels below may not override.
- `SettingValue` and `SettingSource`: resolution as one correlated subquery, so
  a setting can be annotated, filtered, ordered and aggregated on. Nothing is
  merged in Python.
- Values are read as the type their question declares, cast on the database
  side, so a number annotates and queries as a number and a date as a date.
  Non-scalars stay JSON, and `output_field` overrides the lot.
- `get_setting`, `get_settings`, `explain_setting`, `set_setting`,
  `set_settings`, `unset_setting`, `lock_setting` and `unlock_setting`.
- `annotate_settings` and `CascadingSettingsQuerySetMixin`.
- An admin for the levels and the schemas, plus a settings page any model admin
  can show through `CascadingSettingsAdminMixin`.
- A JSON API handing back the questionnaire plan alongside the resolved values,
  and writing only the keys it is given.
- The suite runs against PostgreSQL as well as SQLite -- `TEST_DATABASE=postgres`,
  or a `-pg` factor on any tox environment -- and CI runs the oldest supported
  Django against PostgreSQL 14 and the newest against 17.
- **Tenants**, on the questionnaire scopes 0.2.0 introduced, with one rule of
  this package's own: the global level holds the installation's defaults and
  every tenant reads them, and every level below it belongs to one tenant and is
  read by that tenant alone. `scope=` on the reads, the writes and the
  annotations; a `scope_key` on every stored row and in the provenance; the API
  views read the tenant from a `scope_key` URL prefix. An installation that
  configures no scope model has one scope and notices none of it.
- A second test run against a scope model the package does not own,
  `pytest tests/scoped --ds=tests.settings_scoped`, which tox and CI both run.

### Fixed

- The tox Django matrix installed nothing: the lock runner ignores `deps`, so
  every environment tested whatever `uv.lock` pinned rather than the Django its
  name says. It pins through `commands_pre` now, and prints what it resolved.


[Unreleased]: https://github.com/vintasoftware/vinta-django-cascading-settings/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/vintasoftware/vinta-django-cascading-settings/releases/tag/v0.1.0
