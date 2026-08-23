"""What the agent was asked, what it did, and what a human decided about it.

Three tables rather than one row with a JSON transcript on it. The question a reviewer
asks after a bad recommendation is never about a single run — it is "which runs called
this tool and then recommended a supplier switch", and a blob cannot answer that.

Nothing here runs a model. These tables exist so that the loop cannot run without leaving
a trail, which is the difference between an audit trail and a log nobody kept.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel

# A run is either still going, finished cleanly, or stopped for a reason worth recording.
RUN_STATUSES = ("running", "completed", "failed")
# The three things that can happen in a turn of the loop.
STEP_KINDS = ("model_message", "tool_call", "tool_result")
# `proposed` is the only state the loop may create. The model never approves anything,
# including its own output.
RECOMMENDATION_STATUSES = ("proposed", "approved", "rejected")


class AgentRun(BaseModel):
    """One analysis, from the moment somebody asked for it.

    Token counts live here because "what did this feature cost" is a question the daily
    budget cap can only answer in aggregate, and per-run cost is what decides whether
    scheduled runs are ever affordable.

    `supplier_public_id` is a plain string rather than a foreign key, matching
    `SearchFeedback`: a run is a record of what someone asked and what was said, and it
    has to survive the supplier registry being tidied up underneath it.
    """

    __tablename__ = "agent_runs"

    public_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    requested_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    supplier_public_id: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    step_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    completion_tokens: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # A truncated analysis presented as a finished one is worse than an error, so why a
    # run stopped is a column rather than something to infer from the step count.
    failure_reason: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    __table_args__ = (
        Index("idx_agent_runs_organization", "organization_id"),
        Index("idx_agent_runs_supplier", "supplier_public_id"),
    )


class AgentStep(BaseModel):
    """One turn of the loop: what the model said, what it called, what came back.

    Persisted before the next turn is requested, so a run that crashes mid-loop leaves a
    readable partial transcript. That is the difference between diagnosing a failure and
    guessing at one.
    """

    __tablename__ = "agent_steps"

    run_id: Mapped[int] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    # Explicit rather than inferred from the primary key, which is an implementation
    # detail that any change to insert ordering would quietly break.
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    tool_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "ordinal", name="uq_agent_step_ordinal"),
        Index("idx_agent_steps_tool", "tool_name"),
    )


class AgentRecommendation(BaseModel):
    """A proposed mitigation, and the human decision about it.

    `evidence_event_keys` holds `RiskEvent.event_key` values rather than free text, so
    "show me the evidence" is a join rather than a reading exercise. It is also what
    makes a fabricated citation detectable instead of merely implausible — the
    characteristic failure of this class of system, and the first thing a procurement
    audit would catch.

    The decision is one-way. An approval that can be quietly reversed is not an approval
    trail, so the state machine lives in the API and this table only records where it
    landed.
    """

    __tablename__ = "agent_recommendations"

    run_id: Mapped[int] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_event_keys: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    status: Mapped[str] = mapped_column(String(20), default="proposed", nullable=False)
    # Nulled rather than cascaded, so a decision survives the person who made it
    # leaving — the same reasoning as `Watchlist.created_by_user_id`.
    decided_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    decision_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("run_id", "ordinal", name="uq_agent_recommendation_ordinal"),
        Index("idx_agent_recommendations_status", "status"),
    )
