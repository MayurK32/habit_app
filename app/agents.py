"""
Agent helper functions for parsing habit progress using OpenAI models.

This module defines a function that attempts to call OpenAI's Chat
Completion API to extract structured information from a natural
language summary of the user's daily activities. If the API key is
not configured or the call fails, the function falls back to the
simple heuristic parser from `utils.py`.

The AI is instructed to output JSON mapping habit names to minutes
practised. This JSON is then correlated back to habit IDs based on
the list of known habits.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List

import httpx

from .schemas import HabitRead
from .utils import parse_speech_text


async def parse_habits_with_ai(text: str, habits: List[HabitRead], existing_progress: Dict[str, int] = None) -> Dict[str, int]:
    """
    Use the OpenAI ChatCompletion API to extract habit durations from a
    free‑form description and intelligently handle progress accumulation.
    If the API key is not set or the call fails, fall back to the heuristic parser.

    Args:
        text: The user's daily summary.
        habits: A list of HabitRead objects representing configured habits.
        existing_progress: Dict of habit_id -> existing minutes for today (for accumulation)

    Returns:
        A dictionary mapping habit IDs to NEW minutes to add (not total).
    """
    api_key = os.getenv("OPENAI_API_KEY")
    # Fallback if no API key
    if not api_key:
        return parse_speech_text(text, habits)
    # Build a system prompt that instructs the model to output JSON
    habit_names = [habit.name for habit in habits]
    habit_targets = {habit.name: habit.target_minutes for habit in habits}
    
    # Handle existing progress for intelligent accumulation
    existing_progress = existing_progress or {}
    
    system_prompt = (
        "You are an intelligent habit tracking assistant. I will give you:\n"
        "1. A list of habits with their target minutes\n"
        "2. Any existing progress for today (minutes already logged)\n"
        "3. A new user summary describing recent activity\n\n"
        
        "Your job: Return a JSON object with habit names as keys and NEW minutes to ADD as values.\n\n"
        
        "INTELLIGENT RULES:\n"
        "1. EXPLICIT MINUTES: '15 minutes', '30 mins' → use that EXACT number\n"
        "2. COMPLETION PHRASES: 'completed', 'finished', 'done with', 'accomplished' → "
        "calculate remaining minutes needed to reach target (target - existing)\n"
        "3. ADDITIVE PHRASES: 'another 10 minutes', 'more 15 mins', '10 more' → add that amount\n"
        "4. NO MENTION: If habit not mentioned → return 0\n"
        "5. SMART MATCHING: 'workout' matches 'morning workout', 'meditate' matches 'meditation'\n"
        "6. BE PRECISE: Don't invent or inflate numbers - use exactly what user says\n\n"
        
        "EXAMPLES:\n"
        "- Existing: 20 mins meditation, New: 'completed meditation' → 10 mins (if target is 30)\n"
        "- Existing: 0 mins workout, New: 'finished workout' → 60 mins (full target)\n"
        "- Existing: 15 mins reading, New: 'read for 10 more minutes' → 10 mins\n"
        "- Existing: 0 mins yoga, New: 'did 25 minutes of yoga' → 25 mins (EXACTLY 25)\n"
        "- Existing: 10 mins deep work, New: 'deep work 20 minutes' → 20 mins (EXACTLY 20)\n\n"
        
        "Return ONLY the JSON object with NEW minutes to add, not totals."
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": json.dumps({
                "habits": [{"name": habit.name, "target_minutes": habit.target_minutes} for habit in habits],
                "existing_progress": {habit.name: existing_progress.get(habit.id, 0) for habit in habits},
                "summary": text
            }),
        },
    ]
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-3.5-turbo-0125",
                    "messages": messages,
                    "temperature": 0,
                },
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()
            # Attempt to parse JSON. The model is instructed to return JSON but
            # we guard against stray text.
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1:
                json_str = content[start : end + 1]
                mapping = json.loads(json_str)
            else:
                mapping = {}
    except Exception:
        # Fallback on any error
        return parse_speech_text(text, habits)
    # Correlate habit names back to IDs
    result: Dict[str, int] = {}
    for habit in habits:
        minutes = mapping.get(habit.name, 0)
        try:
            minutes_int = int(minutes)
        except (TypeError, ValueError):
            minutes_int = 0
        result[habit.id] = minutes_int
    return result