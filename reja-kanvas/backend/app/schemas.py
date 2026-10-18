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
Priority = Literal["low", "normal", "high", "urgent"]

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
    code: Optional[str] = Field(default=None, max_length=20)

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


class Recurrence(Model):
    """daily / weekly (optionally on given weekdays, 0 = Monday) / monthly, every `interval` units,
    optionally until a date (inclusive)."""

    freq: Literal["daily", "weekly", "monthly"]
    interval: int = Field(default=1, ge=1, le=30)
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    until: Optional[Date] = None

    @field_validator("weekdays")
    @classmethod
    def _weekdays(cls, v: list[int]) -> list[int]:
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("weekday must be 0..6")
        return sorted(set(v))


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
    priority: Priority = "normal"
    recurrence: Optional[Recurrence] = None
    parent_id: Optional[str] = None
    goal_id: Optional[str] = None
    board_id: Optional[str] = None
    duration_minutes: Optional[int] = Field(default=None, ge=5, le=24 * 60)
    approval_chain: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("parent_id", "goal_id", "board_id")
    @classmethod
    def _refs(cls, v):
        return _uuid(v)

    @field_validator("approval_chain")
    @classmethod
    def _chain(cls, v):
        return [_uuid(x) for x in v]

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
    priority: Optional[Priority] = None
    recurrence: Optional[Recurrence] = None
    parent_id: Optional[str] = None
    goal_id: Optional[str] = None
    duration_minutes: Optional[int] = Field(default=None, ge=5, le=24 * 60)
    approval_chain: Optional[list[str]] = Field(default=None, max_length=4)

    @field_validator("parent_id", "goal_id")
    @classmethod
    def _refs(cls, v):
        return _uuid(v)

    @field_validator("approval_chain")
    @classmethod
    def _chain(cls, v):
        return None if v is None else [_uuid(x) for x in v]

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
        for required in ("title", "color", "x", "y", "goal", "done_criteria", "require_proof", "body_html", "priority", "approval_chain"):
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
    due_at: Optional[datetime] = None
    assignee_id: Optional[str] = None

    @field_validator("due_at")
    @classmethod
    def _due(cls, v):
        return _aware(v)

    @field_validator("assignee_id")
    @classmethod
    def _assignee(cls, v):
        return _uuid(v)


class StepOrder(Model):
    ids: list[str] = Field(min_length=1, max_length=50)


SIGNATURE_MAX = 300_000  # a drawn signature as a PNG data URL


def _signature(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    if not v.startswith("data:image/png;base64,") or len(v) > SIGNATURE_MAX:
        raise ValueError("signature must be a PNG data URL under 300 KB")
    return v


class SubmitIn(Model):
    final_note: str = Field(default="", max_length=2000)
    rating: Optional[Rating] = None
    signature: Optional[str] = None

    @field_validator("signature")
    @classmethod
    def _sig(cls, v):
        return _signature(v)


class ApproveIn(Model):
    signature: Optional[str] = None

    @field_validator("signature")
    @classmethod
    def _sig(cls, v):
        return _signature(v)


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


class DependencyIn(Model):
    blocker_id: str

    @field_validator("blocker_id")
    @classmethod
    def _id(cls, v):
        return _uuid(v)


class CommentIn(Model):
    body: str = Field(min_length=1, max_length=2000)


class TemplateSave(Model):
    name: str = Field(min_length=1, max_length=60)


class PasswordChange(Model):
    current: str = Field(max_length=128)
    new: str = Field(min_length=8, max_length=128)


class DeleteAccount(Model):
    password: str = Field(max_length=128)


class ParseIn(Model):
    text: str = Field(min_length=1, max_length=300)


class ImportIn(Model):
    version: int = 1
    plans: list[dict] = Field(max_length=2000)


# ---- next-stage features ----------------------------------------------------------------------

class TimeEntryIn(Model):
    started_at: datetime
    minutes: int = Field(ge=1, le=24 * 60)
    note: str = Field(default="", max_length=300)

    @field_validator("started_at")
    @classmethod
    def _aware_start(cls, v):
        return _aware(v)


class ReactionIn(Model):
    emoji: Literal["👍", "❤️", "🎉", "✅", "👀", "🙏"]


class GoalIn(Model):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    target_date: Optional[Date] = None
    color: Color = "sky"


class GoalPatch(Model):
    title: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)
    target_date: Optional[Date] = None
    color: Optional[Color] = None
    archived: Optional[bool] = None


class FilterQuery(Model):
    text: str = Field(default="", max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=20)
    priorities: list[Priority] = Field(default_factory=list, max_length=4)
    statuses: list[Literal["active", "pending_approval", "returned", "done", "cancelled"]] = Field(default_factory=list, max_length=5)
    due: Optional[Literal["overdue", "today", "week", "none"]] = None
    mine_only: bool = False


class SavedFilterIn(Model):
    name: str = Field(min_length=1, max_length=60)
    query: FilterQuery


class TeamIn(Model):
    name: str = Field(min_length=1, max_length=60)


class MemberIn(Model):
    email: str = Field(max_length=200)
    role: Literal["admin", "member", "viewer"] = "member"

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return v.lower()


class MemberRole(Model):
    role: Literal["owner", "admin", "member", "viewer"]


class BoardIn(Model):
    name: str = Field(min_length=1, max_length=60)
    team_id: Optional[str] = None

    @field_validator("team_id")
    @classmethod
    def _team(cls, v):
        return _uuid(v)


class BoardRename(Model):
    name: str = Field(min_length=1, max_length=60)


class MoveBoard(Model):
    board_id: Optional[str] = None

    @field_validator("board_id")
    @classmethod
    def _board(cls, v):
        return _uuid(v)


class AssignIn(Model):
    user_id: str

    @field_validator("user_id")
    @classmethod
    def _uid(cls, v):
        return _uuid(v)


class CanvasItemIn(Model):
    id: Optional[str] = None
    board_id: Optional[str] = None
    kind: Literal["note", "frame"]
    x: float = Field(ge=-COORD, le=COORD)
    y: float = Field(ge=-COORD, le=COORD)
    w: float = Field(ge=40, le=8000)
    h: float = Field(ge=40, le=8000)
    text: str = Field(default="", max_length=2000)
    color: Color = "yellow"

    @field_validator("id", "board_id")
    @classmethod
    def _ids(cls, v):
        return _uuid(v)


class CanvasItemPatch(Model):
    x: Optional[float] = Field(default=None, ge=-COORD, le=COORD)
    y: Optional[float] = Field(default=None, ge=-COORD, le=COORD)
    w: Optional[float] = Field(default=None, ge=40, le=8000)
    h: Optional[float] = Field(default=None, ge=40, le=8000)
    text: Optional[str] = Field(default=None, max_length=2000)
    color: Optional[Color] = None


class Prefs(Model):
    email_kinds: list[str] = Field(default_factory=list, max_length=20)
    digest: bool = False
    quiet_start: Optional[str] = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    quiet_end: Optional[str] = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    large_text: bool = False
    high_contrast: bool = False
    onboarded: bool = False


class ForgotIn(Model):
    email: str = Field(max_length=200)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return v.lower().strip()


class ResetIn(Model):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=8, max_length=128)


class TotpCode(Model):
    code: str = Field(min_length=6, max_length=20)


class TotpDisable(Model):
    password: str = Field(max_length=128)
    code: str = Field(min_length=6, max_length=20)


class ApiKeyIn(Model):
    name: str = Field(min_length=1, max_length=60)


WEBHOOK_EVENTS = ("plan.created", "plan.submitted", "plan.completed", "plan.returned", "plan.deleted", "comment.created")


class WebhookIn(Model):
    url: str = Field(min_length=8, max_length=500)
    events: list[Literal["plan.created", "plan.submitted", "plan.completed", "plan.returned", "plan.deleted", "comment.created"]] = Field(min_length=1, max_length=6)


class ExternalImport(Model):
    format: Literal["csv", "todoist", "trello"]
    content: str = Field(min_length=1, max_length=5_000_000)
