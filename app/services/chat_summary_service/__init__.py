"""Chat session summarization service.

Maintains a rolling per-chat summary that is regenerated every N messages
(currently every 10) by folding the latest batch into the previous summary.
"""

from .summarizer import ChatSummarizer, ChatSummaryResult

__all__ = ["ChatSummarizer", "ChatSummaryResult"]
