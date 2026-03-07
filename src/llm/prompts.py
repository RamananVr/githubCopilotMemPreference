"""Prompt templates for LLM classification."""

CLASSIFY_SYSTEM = """You are a classifier for software development conversations.
For each user-assistant exchange, determine:
1. obs_type: exactly one of: bugfix, feature, refactor, discovery, decision, change, other
2. title: a concise 5-10 word title summarizing the exchange

Definitions:
- bugfix: fixing a bug, error, or unexpected behavior
- feature: adding new functionality or capability
- refactor: restructuring code without changing behavior
- discovery: learning, investigating, or understanding something
- decision: making an architectural or design choice
- change: modifying existing behavior or configuration
- other: does not fit any above category

Respond with JSON only. No markdown fencing."""

CLASSIFY_BATCH_USER = """Classify each of these {count} exchanges. Return a JSON array with exactly {count} objects, each having "id", "obs_type", and "title" keys.

{exchanges}"""

SUMMARIZE_SYSTEM = """You are a summarizer for software development sessions.
Given a series of exchanges from a coding session, produce exactly 3 bullet points
summarizing what was accomplished, discovered, or decided. Each bullet should be
one concise sentence. Respond with JSON: {{"bullets": ["...", "...", "..."]}}"""

SUMMARIZE_USER = """Summarize this session ({request_count} exchanges, project: {project_name}):

{exchanges}"""

PREFERENCES_SYSTEM = """You are an extractor of user preferences and decisions from software development conversations.
Look for explicit statements like "I prefer X", "always use Y", "we decided to Z",
"let's go with A", "from now on B", or similar decisive/preferential language.
Only extract clear, actionable preferences — not tentative discussions.
Respond with JSON: {{"preferences": ["preference 1 text", ...]}}
If no preferences found, return {{"preferences": []}}"""

PREFERENCES_USER = """Extract preferences from this session (project: {project_name}):

{exchanges}"""
