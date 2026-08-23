"""One tool-using agent, bounded and on the record.

Every tool is read-only. The agent's context contains article text written by whoever
published the article, so an agent that can write is an agent a press release can
instruct to write.
"""

from .client import AgentClient, AgentTurn, OpenAIAgentClient, ToolCall
from .loop import MAX_STEPS, run_loop

__all__ = ["AgentClient", "AgentTurn", "OpenAIAgentClient", "ToolCall", "MAX_STEPS", "run_loop"]
