"""Stable error codes and the exception hierarchy (SPEC_service.md section 7)."""

from __future__ import annotations

from typing import Any, Sequence

# Stable transport-neutral codes. The HTTP status mapping is part of the
# interface contract (SPEC_service.md section 7).
BAD_REQUEST = "BAD_REQUEST"
PARSE_ERROR = "PARSE_ERROR"
UNAUTHORIZED = "UNAUTHORIZED"
FORBIDDEN = "FORBIDDEN"
NOT_FOUND = "NOT_FOUND"
REVISION_REQUIRED = "REVISION_REQUIRED"
REVISION_CONFLICT = "REVISION_CONFLICT"
COMMENT_PRESERVATION_CONFLICT = "COMMENT_PRESERVATION_CONFLICT"
PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
VALIDATION_ERROR = "VALIDATION_ERROR"
INVALID_DESCRIPTOR = "INVALID_DESCRIPTOR"
SECRET_ACCESS_DENIED = "SECRET_ACCESS_DENIED"
LOCK_TIMEOUT = "LOCK_TIMEOUT"
CALLBACK_TIMEOUT = "CALLBACK_TIMEOUT"
NO_VALID_BACKUP = "NO_VALID_BACKUP"
STORAGE_ERROR = "STORAGE_ERROR"
UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
INTERNAL_ERROR = "INTERNAL_ERROR"

HTTP_STATUS: dict[str, int] = {
    BAD_REQUEST: 400,
    PARSE_ERROR: 400,
    UNAUTHORIZED: 401,
    FORBIDDEN: 403,
    SECRET_ACCESS_DENIED: 403,
    NOT_FOUND: 404,
    REVISION_CONFLICT: 409,
    COMMENT_PRESERVATION_CONFLICT: 409,
    PAYLOAD_TOO_LARGE: 413,
    VALIDATION_ERROR: 422,
    INVALID_DESCRIPTOR: 422,
    REVISION_REQUIRED: 428,
    CALLBACK_TIMEOUT: 504,
    LOCK_TIMEOUT: 503,
    NO_VALID_BACKUP: 404,
    STORAGE_ERROR: 500,
    UNSUPPORTED_CAPABILITY: 501,
    INTERNAL_ERROR: 500,
}


class AisetError(Exception):
    """Base class; carries a stable code, a message and structured issues."""

    code = INTERNAL_ERROR
    status = 500

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        issues: Sequence[dict[str, Any]] | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.issues: list[dict[str, Any]] = list(issues or ())
        self.detail = detail

    @property
    def http_status(self) -> int:
        return HTTP_STATUS.get(self.code, 500)

    def to_envelope(self) -> dict[str, Any]:
        """Transport-neutral error envelope (SPEC_service.md section 7)."""
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.issues:
            error["issues"] = self.issues
        if self.detail:
            error["detail"] = self.detail
        return {"ok": False, "error": error}


class BadRequest(AisetError):
    code = BAD_REQUEST
    status = 400


class ParseError(BadRequest):
    """Malformed JSON5/template source, including duplicate object keys."""

    code = PARSE_ERROR


class PathError(BadRequest):
    """Malformed JSON Pointer, missing parent, or an unsupported address."""


class Unauthorized(AisetError):
    code = UNAUTHORIZED
    status = 401


class Forbidden(AisetError):
    code = FORBIDDEN
    status = 403


class SecretAccessDenied(Forbidden):
    code = SECRET_ACCESS_DENIED


class NotFound(AisetError):
    code = NOT_FOUND
    status = 404


class RevisionRequired(AisetError):
    code = REVISION_REQUIRED
    status = 428


class RevisionConflict(AisetError):
    code = REVISION_CONFLICT
    status = 409


class CommentPreservationConflict(AisetError):
    """A replacement cannot preserve comment attachment (SPEC.md 5.3.5)."""

    code = COMMENT_PRESERVATION_CONFLICT
    status = 409


class PayloadTooLarge(AisetError):
    code = PAYLOAD_TOO_LARGE
    status = 413


class ValidationError(AisetError):
    code = VALIDATION_ERROR
    status = 422


class InvalidDescriptor(AisetError):
    code = INVALID_DESCRIPTOR
    status = 422


class LockTimeout(AisetError):
    code = LOCK_TIMEOUT
    status = 503


class CallbackTimeout(AisetError):
    code = CALLBACK_TIMEOUT
    status = 504


class NoValidBackup(AisetError):
    code = NO_VALID_BACKUP
    status = 404


class StorageError(AisetError):
    code = STORAGE_ERROR
    status = 500


class UnsupportedCapability(AisetError):
    """A recognized capability that this build does not execute yet."""

    code = UNSUPPORTED_CAPABILITY
    status = 501


class DescriptorError(ValueError):
    """Malformed descriptor definition detected while loading/composing."""

    def __init__(self, message: str, *, path: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.path = path

    def as_issue(self, severity: str = "error") -> dict[str, Any]:
        issue: dict[str, Any] = {"path": self.path, "rule": "descriptor", "message": self.message}
        if severity:
            issue["severity"] = severity
        return issue