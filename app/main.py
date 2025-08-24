"""
Entry point for the Habit Tracker FastAPI application.

This module defines the API endpoints for managing habits, recording
progress, parsing speech-transcribed descriptions, and computing
progress bars. The application automatically chooses between an
in-memory repository for testing and a MongoDB-backed repository for
production based on the presence of the `MONGO_URI` environment
variable.

The API is designed with minimalism and ease of use in mind; the
frontend is served as static files under the `/` path and interacts
with the API via JavaScript fetch calls.
"""

import os
from datetime import date
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends

# Load environment variables from .env file
load_dotenv()
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .schemas import (
    HabitCreate,
    HabitRead,
    ProgressCreate,
    ProgressRead,
    SpeechInput,
    ProgressBar,
)
from .repository import HabitRepository, InMemoryRepository, MongoRepository
from .utils import parse_speech_text
from .agents import parse_habits_with_ai


def get_repository() -> HabitRepository:
    """Factory that returns the appropriate repository implementation."""
    mongo_uri = os.getenv("MONGO_URI")
    print("mongo uri"+mongo_uri)
    if mongo_uri:
        return MongoRepository(mongo_uri)
    return InMemoryRepository()


app = FastAPI(title="Habit Tracker API")

# Allow CORS for local development; production should restrict origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event() -> None:
    """Initialize repository on startup."""
    # We attach the repository to the application state for dependency injection
    app.state.repo = get_repository()


def get_repo() -> HabitRepository:
    """Dependency to retrieve the repository instance."""
    return app.state.repo


@app.get("/", response_class=FileResponse)
async def serve_frontend() -> FileResponse:
    """Serve the main HTML file for the frontend."""
    frontend_path = os.path.join(os.path.dirname(__file__), "../frontend/index.html")
    return FileResponse(frontend_path)


# Serve the PWA manifest file
@app.get("/manifest.json", response_class=FileResponse)
async def serve_manifest() -> FileResponse:
    """Return the web app manifest file."""
    manifest_path = os.path.join(os.path.dirname(__file__), "../frontend/manifest.json")
    return FileResponse(manifest_path)


# Serve the service worker script
@app.get("/service-worker.js", response_class=FileResponse)
async def serve_service_worker() -> FileResponse:
    """Return the service worker for offline caching."""
    sw_path = os.path.join(os.path.dirname(__file__), "../frontend/service-worker.js")
    return FileResponse(sw_path, media_type="application/javascript")


# Mount static assets (CSS/JS) relative to this file
static_dir = os.path.join(os.path.dirname(__file__), "../frontend")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.post("/habits", response_model=HabitRead)
async def create_habit(habit: HabitCreate, repo: HabitRepository = Depends(get_repo)) -> HabitRead:
    """Create a new habit."""
    return await repo.create_habit(habit)


@app.get("/habits", response_model=List[HabitRead])
async def list_habits(repo: HabitRepository = Depends(get_repo)) -> List[HabitRead]:
    """Return all habits."""
    return await repo.list_habits()


@app.post("/progress", response_model=ProgressRead)
async def record_progress(
    progress: ProgressCreate, repo: HabitRepository = Depends(get_repo)
) -> ProgressRead:
    """Record minutes practised for a habit on a given date."""
    try:
        return await repo.record_progress(progress)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/progress/{progress_date}", response_model=List[ProgressRead])
async def get_progress_for_date(
    progress_date: date, repo: HabitRepository = Depends(get_repo)
) -> List[ProgressRead]:
    """Get progress entries for a specific date."""
    return await repo.get_progress_for_date(progress_date)


@app.get("/progress/bars/{progress_date}", response_model=List[ProgressBar])
async def get_progress_bars(
    progress_date: date, repo: HabitRepository = Depends(get_repo)
) -> List[ProgressBar]:
    """Compute progress ratios for all habits on a specific date."""
    return await repo.compute_progress_bars(progress_date)


@app.post("/speech", response_model=List[ProgressRead])
async def handle_speech_input(
    speech: SpeechInput, repo: HabitRepository = Depends(get_repo)
) -> List[ProgressRead]:
    """
    Accept transcribed speech describing daily habits and automatically
    update progress entries for the current day. For each habit that
    appears in the text, we attempt to extract the minutes practised
    and record the progress. If no explicit minutes are found near
    the habit name, we assume the user completed the full target.
    """
    # Determine today's date in the user's timezone. The specification
    # mentions Asia/Kolkata, but for generality we use date.today() here.
    today = date.today()
    habits = await repo.list_habits()
    
    # Get existing progress for today to enable intelligent accumulation
    existing_progress_list = await repo.get_progress_for_date(today)
    existing_progress = {entry.habit_id: entry.minutes for entry in existing_progress_list}
    
    # Use the AI parser with existing progress for intelligent accumulation
    minutes_map = await parse_habits_with_ai(speech.text, habits, existing_progress)
    results: List[ProgressRead] = []
    
    for habit_id, new_minutes in minutes_map.items():
        if new_minutes > 0:  # Only process if AI detected activity
            # AI returns NEW minutes to add, we need to accumulate with existing
            current_minutes = existing_progress.get(habit_id, 0)
            total_minutes = current_minutes + new_minutes
            
            
            # Create progress entry with total accumulated minutes
            progress = ProgressCreate(habit_id=habit_id, date=today, minutes=total_minutes)
            try:
                result = await repo.record_progress(progress)
                results.append(result)
            except ValueError:
                continue
    return results