"""agent runs, steps and recommendations

Revision ID: u6v7w8_agent_runs
Revises: t5u6v7_search_feedback

The durable record behind D6's "full audit trail". Three tables rather than a run row
with a JSON transcript on it: the question asked after a bad recommendation is always
about a pattern across runs — which ones called a given tool and then proposed a supplier
switch — and a blob cannot be queried that way.

`agent_steps.ordinal` and `agent_recommendations.ordinal` are unique per run. Order is
explicit rather than inferred from the primary key, which is an implementation detail
that any change to insert ordering would quietly break.

`evidence_event_keys` holds RiskEvent.event_key values, which is what makes a fabricated
citation detectable rather than merely implausible.

Deleting an organization or a user takes their runs with them; a decision keeps its
author as SET NULL so an approval survives the approver leaving.
"""

import sqlalchemy as sa
from alembic import op

revision = "u6v7w8_agent_runs"
down_revision = "t5u6v7_search_feedback"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        *_timestamps(),
        sa.Column("public_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("supplier_public_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("step_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("failure_reason", sa.String(length=100), nullable=True),
    )
    op.create_index("idx_agent_runs_organization", "agent_runs", ["organization_id"])
    op.create_index("idx_agent_runs_supplier", "agent_runs", ["supplier_public_id"])

    op.create_table(
        "agent_steps",
        *_timestamps(),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint("run_id", "ordinal", name="uq_agent_step_ordinal"),
    )
    op.create_index("idx_agent_steps_tool", "agent_steps", ["tool_name"])

    op.create_table(
        "agent_recommendations",
        *_timestamps(),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("evidence_event_keys", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="proposed"),
        sa.Column(
            "decided_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.UniqueConstraint("run_id", "ordinal", name="uq_agent_recommendation_ordinal"),
    )
    op.create_index("idx_agent_recommendations_status", "agent_recommendations", ["status"])


def downgrade() -> None:
    op.drop_index("idx_agent_recommendations_status", table_name="agent_recommendations")
    op.drop_table("agent_recommendations")
    op.drop_index("idx_agent_steps_tool", table_name="agent_steps")
    op.drop_table("agent_steps")
    op.drop_index("idx_agent_runs_supplier", table_name="agent_runs")
    op.drop_index("idx_agent_runs_organization", table_name="agent_runs")
    op.drop_table("agent_runs")
