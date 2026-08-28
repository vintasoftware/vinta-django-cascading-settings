"""What type a setting comes back as, and the cast that makes it so.

A value is stored as JSON, and JSON compares as JSON: ``10`` sorts next to
``"10"``, and ``>`` means nothing.  So the subquery reads the scalar out of the
JSON and casts it, in SQL, to the type the question says it is -- a number
annotates as a number, and is filtered, ordered and summed as one.

What each type is comes from the definition rather than the caller.  The one
thing the definition cannot say by type alone is whether a number is a whole
one, so that is read from the question's own validator chain: a ``number`` that
declares the ``integer`` validator is an integer, and every other number is a
float.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db.models import (
    DateField,
    DateTimeField,
    Field,
    FloatField,
    Func,
    IntegerField,
    TextField,
    TimeField,
)
from vinta_django_questionnaires.models import Question
from vinta_django_questionnaires.question_types import QuestionType

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.db.models import QuerySet

#: The validator a whole number declares.
INTEGER_VALIDATOR = "integer"

#: What each scalar question type is read as. Everything absent stays JSON,
#: because a list, a range, a matrix or a nested answer set is not a scalar and
#: has nothing to be cast to.
OUTPUT_FIELDS: dict[str, type[Field[Any, Any]]] = {
    QuestionType.FREE_TEXT: TextField,
    QuestionType.URL: TextField,
    QuestionType.SINGLE_CHOICE: TextField,
    QuestionType.SINGLE_SELECT: TextField,
    QuestionType.MONTH: TextField,
    QuestionType.NUMBER: FloatField,
    QuestionType.TIME_DURATION: FloatField,
    QuestionType.YEAR: IntegerField,
    QuestionType.DATE: DateField,
    QuestionType.DATE_TIME: DateTimeField,
    QuestionType.TIME: TimeField,
}

#: The types whose question may declare itself whole.
COUNTABLE = frozenset({QuestionType.NUMBER, QuestionType.TIME_DURATION})


class JSONScalar(Func):
    """The scalar inside a JSON value, as SQL rather than as JSON.

    Every backend spells this differently, and none of them lets a JSON column
    be cast straight to a number: PostgreSQL will not cast ``jsonb`` to
    anything but text, and the others hand back the quotes along with a string.
    """

    arity = 1
    function = "JSON_EXTRACT"
    template = "%(function)s(%(expressions)s, '$')"
    output_field = TextField()

    def as_postgresql(self, compiler: Any, connection: Any, **extra: Any) -> Any:
        return self.as_sql(compiler, connection, template="(%(expressions)s #>> '{}')", **extra)

    def as_mysql(self, compiler: Any, connection: Any, **extra: Any) -> Any:
        return self.as_sql(
            compiler,
            connection,
            template="JSON_UNQUOTE(JSON_EXTRACT(%(expressions)s, '$'))",
            **extra,
        )

    def as_oracle(self, compiler: Any, connection: Any, **extra: Any) -> Any:
        return self.as_sql(
            compiler, connection, template="JSON_VALUE(%(expressions)s, '$')", **extra
        )


def output_field_for(key: str, *, schema: str | None = None) -> Field[Any, Any] | None:
    """The type *key* is read as, or ``None`` to leave its values as JSON.

    Every version of every settings questionnaire that asks *key* has to agree
    on what it is.  When they do not -- two schemas asking the same key of
    different types, or a type that changed between versions -- the values stay
    JSON, because one cast cannot be right for both.
    """
    questions = list(settings_questions(key, schema=schema))
    if not questions:
        return None
    question_types = {question.question_type for question in questions}
    if len(question_types) != 1:
        return None
    question_type = question_types.pop()
    field = OUTPUT_FIELDS.get(question_type)
    if field is None:
        return None
    if question_type in COUNTABLE and _all_whole(questions):
        return IntegerField()
    return field()


def settings_questions(key: str, *, schema: str | None = None) -> QuerySet[Question]:
    """Every question a settings schema asks under *key*."""
    held = "section__page__questionnaire_version__questionnaire__settings_schema"
    queryset = Question.objects.filter(key=key).exclude(**{f"{held}__isnull": True})
    if schema is None:
        queryset = queryset.filter(**{f"{held}__is_active": True})
    else:
        queryset = queryset.filter(**{f"{held}__key": schema})
    return queryset.prefetch_related("validators")


def _all_whole(questions: Iterable[Question]) -> bool:
    """Whether every one of *questions* says its number is a whole one."""
    return all(
        any(
            binding.validator == INTEGER_VALIDATOR and binding.is_enabled
            for binding in question.validators.all()
        )
        for question in questions
    )


__all__ = [
    "COUNTABLE",
    "INTEGER_VALIDATOR",
    "OUTPUT_FIELDS",
    "JSONScalar",
    "output_field_for",
    "settings_questions",
]
