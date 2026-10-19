"""API error model. Every error response has the same JSON shape:

{"error": {"code": "EMPLOYEE_DUPLICATE", "message": "...", "details": {...}, "request_id": "..."}}
"""

from __future__ import annotations


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def bad_request(message: str, code: str = "BAD_REQUEST", **details) -> ApiError:
    return ApiError(400, code, message, details)


def unauthorized(message: str = "Authentication required", code: str = "UNAUTHORIZED") -> ApiError:
    return ApiError(401, code, message)


def forbidden(message: str = "You do not have permission for this action", code: str = "FORBIDDEN", **details) -> ApiError:
    return ApiError(403, code, message, details)


def not_found(what: str = "Resource") -> ApiError:
    return ApiError(404, "NOT_FOUND", f"{what} not found")


def conflict(message: str, code: str = "CONFLICT", **details) -> ApiError:
    return ApiError(409, code, message, details)


def gone(message: str, code: str = "GONE") -> ApiError:
    return ApiError(410, code, message)


def locked(message: str, code: str = "LOCKED", **details) -> ApiError:
    return ApiError(423, code, message, details)


def unprocessable(message: str, code: str = "VALIDATION_ERROR", **details) -> ApiError:
    return ApiError(422, code, message, details)


def too_many(retry_after: int) -> ApiError:
    return ApiError(429, "RATE_LIMITED", f"Too many requests, retry in {retry_after} s", {"retry_after": retry_after})


def payment_required(message: str, code: str = "SUBSCRIPTION_RESTRICTED") -> ApiError:
    return ApiError(402, code, message)
