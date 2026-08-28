"""Settings for the test project.

The suite runs on SQLite by default and on PostgreSQL when ``TEST_DATABASE`` says
so, because the resolver is SQL and the two backends do not agree about all of
it -- what a subquery may refer to, and how a scalar comes out of a JSON column.
"""

from __future__ import annotations

import os

SECRET_KEY = "vinta_django_cascading_settings-tests"
DEBUG = False
USE_TZ = True

if os.environ.get("TEST_DATABASE", "sqlite") == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("PGDATABASE", "cascading_settings"),
            "USER": os.environ.get("PGUSER", "postgres"),
            "PASSWORD": os.environ.get("PGPASSWORD", "postgres"),
            "HOST": os.environ.get("PGHOST", "127.0.0.1"),
            "PORT": os.environ.get("PGPORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.messages",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "vinta_django_questionnaires",
    "vinta_django_cascading_settings",
    "tests.testapp",
]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "tests.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

# The questionnaire structure editor posts a whole definition in one form.
DATA_UPLOAD_MAX_NUMBER_FIELDS = 5000

STATIC_URL = "/static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING_CONFIG = None
