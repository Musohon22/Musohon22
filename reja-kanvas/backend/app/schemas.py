import re
import uuid
from datetime import date as Date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import timeutil

Color = Literal["yellow", "mint", "lilac", "peach", "sky", "white"]
Lang = Literal["uz", "uz-Cyrl", "ru", "en"]
StepStatus = Literal["todo", "done", "cancelled"]
Rating = Literal["excellent", "good", "partial"]

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
COORD = 100_000


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _uuid(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return str(uuid.UUID(value))


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is not None and value.tzinfo is None:
        raise ValueError("timezone required")
    return value


class RegisterIn(Model):
    email: str = Field(max_length=200)
    name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8, max_length=128)
    tz: str = "Asia/Tashkent"
    lang: Lang = "uz"

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        if not _EMAIL.match(v):
            raise ValueError("invalid email")
        return v.lower()

    @field_validator("tz")
    @classmethod
    def _tz(cls, v: str) -> str:
        if not timeutil.is_valid_zone(v):
            raise ValueError("unknown timezone")
        return v


class LoginIn(Model):
    email: str = Field(max_length=200)
    password: str = Field(max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return v.lower()


class MeUpdate(Model):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    tz: Optional[str] = None
    lang: Optional[Lang] = None

    @field_validator("tz")
    @classmethod
    def _tz(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not timeutil.is_valid_zone(v):
            raise ValueError("unknown timezone")
        return v


class _PlanFields(Model):
    title: str = Field(min_length=1, max_length=200)
    body_html: str = Field(default="", max_length=200_000)
    tag: Optional[str] = Field(default=None, max_length=30)
    color: Color = "yellow"
    x: float = Field(default=0, ge=-COORD, le=COORD)
    y: float = Field(default=0, ge=-COORD, le=COORD)
    due_at: Optional[datetime] = None
    remind_minutes: Optional[int] = Field(default=None, ge=0, le=10080)
    goal: str = Field(default="", max_length=2000)
    done_criteria: str = Field(default="", max_length=2000)
    require_proof: bool = False
    approver_id: Optional[str] = None
    backup_approver_id: Optional[str] = None

    @field_validator("due_at")
    @classmethod
    def _due(cls, v):
        return _aware(v)

    @field_validator("approver_id", "backup_approver_id")
    @classmethod
    def _ids(cls, v):
        return _uuid(v)


class PlanCreate(_PlanFields):
    id: Optional[str] = None
    steps: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("id")
    @classmethod
    def _id(cls, v):
        return _uuid(v)

    @field_validator("steps")
    @classmethod
    def _steps(cls, v: list[str]) -> list[str]:
        cleaned = [s.strip() for s in v if s.strip()]
        if any(len(s) > 300 for s in cleaned):
            raise ValueError("step too long")
        return cleaned


class PlanPatch(Model):
    """Every field optional; only the fields sent are changed. base_version is the version the
    client's edit started from, used to detect edits made meanwhile on another device."""

    base_version: int = Field(ge=1)
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    body_html: Optional[str] = Field(default=None, max_length=200_000)
    tag: Optional[str] = Field(default=None, max_length=30)
    color: Optional[Color] = None
    x: Optional[float] = Field(default=None, ge=-COORD, le=COORD)
    y: Optional[float] = Field(default=None, ge=-COORD, le=COORD)
    due_at: Optional[datetime] = None
    remind_minutes: Optional[int] = Field(default=None, ge=0, le=10080)
    goal: Optional[str] = Field(default=None, max_length=2000)
    done_criteria: Optional[str] = Field(default=None, max_length=2000)
    require_proof: Optional[bool] = None
    approver_id: Optional[str] = None
    backup_approver_id: Optional[str] = None

    @field_validator("due_at")
    @classmethod
    def _due(cls, v):
        return _aware(v)

    @field_validator("approver_id", "backup_approver_id")
    @classmethod
    def _ids(cls, v):
        return _uuid(v)

    def changes(self) -> dict:
        data = {k: getattr(self, k) for k in self.model_fields_set if k != "base_version"}
        for required in ("title", "color", "x", "y", "goal", "done_criteria", "require_proof", "body_html"):
            if required in data and data[required] is None:
                raise ValueError(f"{required} cannot be null")
        return data


class MoveItem(Model):
    id: str
    x: float = Field(ge=-COORD, le=COORD)
    y: float = Field(ge=-COORD, le=COORD)


class BatchMove(Model):
    items: list[MoveItem] = Field(min_length=1, max_length=500)


class StepCreate(Model):
    id: Optional[str] = None
    text: str = Field(min_length=1, max_length=300)
    position: Optional[int] = Field(default=None, ge=0)

    @field_validator("id")
    @classmethod
    def _id(cls, v):
        return _uuid(v)


class StepPatch(Model):
    text: Optional[str] = Field(default=None, min_length=1, max_length=300)
    status: Optional[StepStatus] = None
    position: Optional[int] = Field(default=None, ge=0)


class SubmitIn(Model):
    final_note: str = Field(default="", max_length=2000)
    rating: Optional[Rating] = None


class RejectIn(Model):
    reason: str = Field(min_length=3, max_length=1000)


class ReopenIn(Model):
    reason: Literal["undo", "reopen", "withdraw"] = "reopen"
    note: str = Field(default="", max_length=1000)


class RescheduleIn(Model):
    ids: list[str] = Field(min_length=1, max_length=200)
    action: Literal["today", "date", "cancel"]
    date: Optional[Date] = None


class ShareCreate(Model):
    role: Literal["view", "edit"] = "view"
    expires_in_days: int = Field(default=7, ge=1, le=90)


class SharedPatch(Model):
    base_version: int = Field(ge=1)
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    body_html: Optional[str] = Field(default=None, max_length=200_000)

    def changes(self) -> dict:
        return {k: getattr(self, k) for k in self.model_fields_set if k != "base_version" and getattr(self, k) is not None}


class ReadNotifications(Model):
    ids: Optional[list[int]] = Field(default=None, max_length=500)


class ApplyTemplate(Model):
    pass
