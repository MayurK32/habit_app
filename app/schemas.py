"""
Pydantic schemas for the Habit Tracker API.

These data models define the structure of requests and responses used by
the FastAPI application. Keeping schemas separate from the database
models helps decouple the API layer from persistence concerns and
makes it easier to write tests against pure Python objects.
"""

from datetime import date as dt_date
from typing import Optional, List

from pydantic import BaseModel, Field


class HabitCreate(BaseModel):
    """Schema for creating a new habit via the API."""

    name: str = Field(..., description="Name of the habit to track.")
    time_block: str = Field(
        ...,
        description=(
            "Time block when this habit occurs, such as 'morning', 'afternoon',"
            " 'evening', or 'night'."
        ),
    )
    target_minutes: int = Field(
        ..., gt=0, description="Number of minutes per day the habit should be practised."
    )


class HabitRead(BaseModel):
    """Schema returned when reading a habit from the API."""

    id: str
    name: str
    time_block: str
    target_minutes: int

    class Config:
        from_attributes = True


class ProgressCreate(BaseModel):
    """Schema for recording a progress entry for a habit on a given date."""

    habit_id: str = Field(..., description="Identifier of the habit.")
    date: dt_date = Field(..., description="Date when the habit was practised.")
    minutes: int = Field(
        ...,
        ge=0,
        description=(
            "Number of minutes performed for the habit on the given date. If"
            " minutes equals or exceeds the target_minutes, the habit is"
            " considered complete."
        ),
    )


class ProgressRead(BaseModel):
    """Schema returned when reading progress information."""

    habit_id: str
    date: dt_date
    minutes: int
    completed: bool


class SpeechInput(BaseModel):
    """Schema for sending speech-transcribed text to the AI parser."""

    text: str = Field(..., description="Transcribed speech describing daily habits.")


class ProgressBar(BaseModel):
    """Schema representing progress for a habit relative to its target."""

    habit_id: str
    progress_ratio: float = Field(
        ..., description="Progress ratio between 0 and 1 indicating completion level."
    )