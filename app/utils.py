"""
Utility functions for the habit tracker application.

This module contains helpers that are not tied to any particular
framework or persistence mechanism. One of the main helpers defined
here is a very simple natural language parser that attempts to
extract habit progress from a free-form string. The parser is not
intended to be robust for all scenarios; instead it is good enough
for the scope of this assignment and can be replaced by a more
sophisticated AI model in the future.
"""

import re
from typing import Dict, List

from .schemas import HabitRead


def parse_speech_text(text: str, habits: List[HabitRead]) -> Dict[str, int]:
    """
    Parse a natural language description of habit completion and return a
    mapping from habit_id to minutes practised.

    The function performs a case-insensitive search for each habit name
    within the input text. If a habit name is found, the parser looks
    for a number (integer) in the vicinity (within a few words) and
    interprets that as the number of minutes practised. If no number
    is found near the habit name, the function assumes the habit was
    completed fully and uses the habit's target_minutes as the value.

    Args:
        text: The free-form description of the day's activities.
        habits: List of habits with IDs and target durations.

    Returns:
        A dict mapping habit IDs to minutes practised.
    """
    result: Dict[str, int] = {}
    lower_text = text.lower()
    tokens = re.split(r"\s+", lower_text)

    # Precompute mapping of habit name tokens to HabitRead for quick lookup.
    # We'll split habit names into tokens and search for those tokens in the text.
    for habit in habits:
        name_tokens = habit.name.lower().split()
        # Find all occurrences of the first token in the tokens list
        for idx, token in enumerate(tokens):
            if token == name_tokens[0]:
                # check subsequent tokens for match
                end_idx = idx + len(name_tokens)
                if tokens[idx:end_idx] == name_tokens:
                    # Look for a number within 5 tokens after the matched phrase
                    window_tokens = tokens[end_idx : end_idx + 5]
                    minutes = None
                    for t in window_tokens:
                        if t.isdigit():
                            minutes = int(t)
                            break
                        # also handle patterns like '15mins' or '15minutes'
                        m = re.match(r"(\d+)(?:min|mins|minutes)?", t)
                        if m:
                            minutes = int(m.group(1))
                            break
                    # If not found ahead, look backwards up to 5 tokens
                    if minutes is None:
                        window_tokens_back = tokens[max(idx - 5, 0) : idx]
                        for t_back in reversed(window_tokens_back):
                            if t_back.isdigit():
                                minutes = int(t_back)
                                break
                            m_back = re.match(r"(\d+)(?:min|mins|minutes)?", t_back)
                            if m_back:
                                minutes = int(m_back.group(1))
                                break
                    # If no explicit minutes found, default to target minutes
                    if minutes is None:
                        minutes = habit.target_minutes
                    # Store the result for this habit
                    result[habit.id] = minutes
                    # Once matched, break out to avoid duplicate updates
                    break

    return result