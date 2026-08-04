"""Stable command-error envelopes and HTTP exception mapping."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import model_validator

from .models import NonEmptyString, StrictModel


CommandErrorCode = Literal[
    "AUTHENTICATION_REQUIRED",
    "DELEGATION_NOT_ACTIVE",
    "COMMAND_SCHEMA_INVALID",
    "COMMAND_DIGEST_MISMATCH",
    "IDEMPOTENCY_KEY_REUSED",
    "INVALID_TRANSITION",
    "RUN_ALREADY_SUBMITTED",
    "CANCELLATION_REQUESTED",
    "CONTROL_HEAD_STALE",
    "STALE_BASIS",
    "TARGET_STATE_MISMATCH",
    "TARGET_NOT_FOUND",
    "DEPENDENCY_CLOSURE_INCOMPLETE",
    "NO_STATE_CHANGE",
    "PUBLICATION_CONFLICT",
    "CUSTOMIZATION_CONFLICT",
    "ROLE_PROVISIONING_FAILED",
]
ErrorCategory = Literal[
    "authentication",
    "authorization",
    "schema",
    "digest",
    "idempotency",
    "transition",
    "concurrency",
    "dependency",
]


@dataclass(frozen=True, slots=True)
class ErrorRule:
    category: ErrorCategory
    http_status: int
    retryable: bool
    rule_id: str


ERROR_RULES: dict[CommandErrorCode, ErrorRule] = {
    "AUTHENTICATION_REQUIRED": ErrorRule("authentication", 401, True, "MH-59"),
    "DELEGATION_NOT_ACTIVE": ErrorRule("authorization", 403, True, "MH-55"),
    "COMMAND_SCHEMA_INVALID": ErrorRule("schema", 422, True, "MH-59"),
    "COMMAND_DIGEST_MISMATCH": ErrorRule("digest", 422, True, "MH-57"),
    "IDEMPOTENCY_KEY_REUSED": ErrorRule("idempotency", 409, True, "MH-49"),
    "INVALID_TRANSITION": ErrorRule("transition", 409, False, "MH-59"),
    "RUN_ALREADY_SUBMITTED": ErrorRule("transition", 409, False, "MH-59"),
    "CANCELLATION_REQUESTED": ErrorRule("concurrency", 409, False, "MH-59"),
    "CONTROL_HEAD_STALE": ErrorRule("concurrency", 409, True, "MH-49"),
    "STALE_BASIS": ErrorRule("concurrency", 409, True, "MH-49"),
    "TARGET_STATE_MISMATCH": ErrorRule("concurrency", 409, True, "MH-49"),
    "TARGET_NOT_FOUND": ErrorRule("dependency", 404, False, "MH-59"),
    "DEPENDENCY_CLOSURE_INCOMPLETE": ErrorRule("dependency", 422, True, "MH-59"),
    "NO_STATE_CHANGE": ErrorRule("transition", 409, False, "MH-47"),
    "PUBLICATION_CONFLICT": ErrorRule("concurrency", 409, True, "MH-56"),
    "CUSTOMIZATION_CONFLICT": ErrorRule("transition", 409, False, "MH-49"),
    "ROLE_PROVISIONING_FAILED": ErrorRule("transition", 500, True, "MH-59"),
}


class CommandError(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    error_id: NonEmptyString
    code: CommandErrorCode
    category: ErrorCategory
    http_status: int
    retryable: bool
    rule_id: NonEmptyString
    object_refs: list[str]
    field_path: NonEmptyString | None = None
    researcher_message: NonEmptyString
    smallest_correction: NonEmptyString
    occurred_at: NonEmptyString

    @model_validator(mode="after")
    def enforce_stable_rule_mapping(self) -> "CommandError":
        expected = ERROR_RULES[self.code]
        actual = (
            self.category,
            self.http_status,
            self.retryable,
            self.rule_id,
        )
        required = (
            expected.category,
            expected.http_status,
            expected.retryable,
            expected.rule_id,
        )
        if actual != required:
            raise ValueError(f"{self.code} must use its registered error mapping")
        return self


class CommandRejected(Exception):
    """Application-service rejection that is safe to expose to clients."""

    def __init__(self, error: CommandError) -> None:
        super().__init__(error.researcher_message)
        self.error = error


def new_command_error(
    code: CommandErrorCode,
    *,
    researcher_message: str,
    smallest_correction: str,
    object_refs: list[str] | None = None,
    field_path: str | None = None,
) -> CommandError:
    rule = ERROR_RULES[code]
    occurred_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return CommandError(
        error_id=f"error.{uuid4()}",
        code=code,
        category=rule.category,
        http_status=rule.http_status,
        retryable=rule.retryable,
        rule_id=rule.rule_id,
        object_refs=object_refs or [],
        field_path=field_path,
        researcher_message=researcher_message,
        smallest_correction=smallest_correction,
        occurred_at=occurred_at,
    )


def command_schema_error(field_path: str | None = None) -> CommandError:
    return new_command_error(
        "COMMAND_SCHEMA_INVALID",
        field_path=field_path,
        researcher_message="The command does not match the required request structure.",
        smallest_correction="Correct the identified field and submit a new command.",
    )


def command_error_response(error: CommandError) -> JSONResponse:
    return JSONResponse(
        status_code=error.http_status,
        content=error.model_dump(mode="json", exclude_none=True),
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(CommandRejected)
    async def handle_command_rejected(
        _request: Request, exception: CommandRejected
    ) -> JSONResponse:
        return command_error_response(exception.error)

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        _request: Request, exception: RequestValidationError
    ) -> JSONResponse:
        first = exception.errors()[0] if exception.errors() else None
        location = None
        if first is not None:
            location = ".".join(str(item) for item in first.get("loc", ())) or None
        return command_error_response(command_schema_error(location))
