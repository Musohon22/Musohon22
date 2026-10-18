class ApiError(Exception):
    """An error the client can act on. `code` is stable and translated by the frontend."""

    def __init__(self, http_status: int, code: str, message: str = "", **details):
        super().__init__(message or code)
        self.status = http_status
        self.code = code
        self.message = message or code
        self.details = details

    def to_dict(self) -> dict:
        return {"error": self.code, "message": self.message, **self.details}


def not_found(what: str = "plan") -> ApiError:
    return ApiError(404, f"{what}_not_found")


def forbidden(code: str = "forbidden") -> ApiError:
    return ApiError(403, code)
