"""Vague context summarization service.

Maintains and updates a project's long-term "vague context" — a compact,
evergreen summary of project facts, architecture cues, prior incidents
and user intent patterns — by folding in the latest chat session.
"""

from .summarizer import VagueContextSummarizer, VagueContextResult

__all__ = ["VagueContextSummarizer", "VagueContextResult"]
