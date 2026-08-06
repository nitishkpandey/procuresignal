"""Tasks that gave up."""

from typing import Optional

from sqlalchemy import JSON, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class DeadLetter(BaseModel):
    """One task that exhausted its retries.

    Without this the work simply vanishes into the logs: nobody is told, and the system
    keeps reporting healthy while the articles never arrive. A poison message also
    retries forever, so the queue quietly fills behind it.
    """

    __tablename__ = "dead_letters"

    task_name: Mapped[str] = mapped_column(String(200), nullable=False)
    task_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    # Scrubbed with the audit log's scrubber, since task arguments carry credentials
    # and whoever is on call reads this.
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error_type: Mapped[str] = mapped_column(String(200), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    traceback: Mapped[str] = mapped_column(Text, nullable=False)
    retries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        Index("idx_dead_letter_task", "task_name"),
        Index("idx_dead_letter_created", "created_at"),
    )
