"""
Repositories abstract the persistence layer from the application logic.

This module defines base repository interfaces for managing habits and
progress entries as well as concrete implementations for in-memory
storage (used for testing) and MongoDB (used in production). Having a
repository layer allows us to swap out the storage backend without
changing the API logic.
"""

from __future__ import annotations

from datetime import date
from typing import List, Dict, Optional
import os

try:
    # Motor is an optional dependency. When running tests without a MongoDB
    # backend, this import may fail. We import lazily in MongoRepository
    from motor.motor_asyncio import AsyncIOMotorClient  # type: ignore
    from bson import ObjectId  # type: ignore
except ModuleNotFoundError:
    AsyncIOMotorClient = None  # type: ignore
    ObjectId = None  # type: ignore

from .schemas import HabitCreate, HabitRead, ProgressCreate, ProgressRead, ProgressBar


class HabitRepository:
    """Interface for habit persistence backends."""

    async def create_habit(self, habit: HabitCreate) -> HabitRead:
        raise NotImplementedError

    async def list_habits(self) -> List[HabitRead]:
        raise NotImplementedError

    async def get_habit(self, habit_id: str) -> Optional[HabitRead]:
        raise NotImplementedError

    async def record_progress(self, progress: ProgressCreate) -> ProgressRead:
        raise NotImplementedError

    async def get_progress_for_date(self, date: date) -> List[ProgressRead]:
        raise NotImplementedError

    async def compute_progress_bars(self, date: date) -> List[ProgressBar]:
        raise NotImplementedError


class InMemoryRepository(HabitRepository):
    """Simple in-memory repository for tests and local development.

    Habits are stored in a dictionary keyed by their generated ID. Progress
    entries are stored in a nested dictionary keyed by habit_id and date.
    """

    def __init__(self) -> None:
        self._habits: Dict[str, HabitRead] = {}
        self._progress: Dict[str, Dict[date, ProgressRead]] = {}
        self._id_counter = 0

    async def create_habit(self, habit: HabitCreate) -> HabitRead:
        self._id_counter += 1
        habit_id = str(self._id_counter)
        habit_read = HabitRead(
            id=habit_id,
            name=habit.name,
            time_block=habit.time_block,
            target_minutes=habit.target_minutes,
        )
        self._habits[habit_id] = habit_read
        return habit_read

    async def list_habits(self) -> List[HabitRead]:
        return list(self._habits.values())

    async def get_habit(self, habit_id: str) -> Optional[HabitRead]:
        return self._habits.get(habit_id)

    async def record_progress(self, progress: ProgressCreate) -> ProgressRead:
        habit = self._habits.get(progress.habit_id)
        if not habit:
            raise ValueError(f"Habit with id {progress.habit_id} not found")
        completed = progress.minutes >= habit.target_minutes
        progress_entry = ProgressRead(
            habit_id=progress.habit_id,
            date=progress.date,
            minutes=progress.minutes,
            completed=completed,
        )
        self._progress.setdefault(progress.habit_id, {})[progress.date] = progress_entry
        return progress_entry

    async def get_progress_for_date(self, date: date) -> List[ProgressRead]:
        results: List[ProgressRead] = []
        for habit_id, records in self._progress.items():
            if date in records:
                results.append(records[date])
        return results

    async def compute_progress_bars(self, date: date) -> List[ProgressBar]:
        bars: List[ProgressBar] = []
        for habit_id, habit in self._habits.items():
            progress_entry = self._progress.get(habit_id, {}).get(date)
            minutes = progress_entry.minutes if progress_entry else 0
            ratio = min(minutes / habit.target_minutes, 1.0)
            bars.append(ProgressBar(habit_id=habit_id, progress_ratio=ratio))
        return bars


class MongoRepository(HabitRepository):
    """MongoDB-backed repository for production use.

    This implementation uses Motor, an asynchronous MongoDB driver. The
    repository expects a MongoDB database with two collections: `habits`
    and `progress`. Each habit document stores name, time block, and
    target minutes. Progress documents reference a habit via
    `habit_id`, store the date as ISO string, and the minutes practised.
    """

    def __init__(self, mongo_uri: str, db_name: str = "habit_app") -> None:
        # Delay import of motor until initialisation time to avoid optional dependency issues.
        if AsyncIOMotorClient is None or ObjectId is None:
            raise ImportError(
                "Motor is required for MongoRepository but is not installed."
            )
        self._client = AsyncIOMotorClient(mongo_uri)
        self._db = self._client[db_name]
        self._habits = self._db["habits"]
        self._progress = self._db["progress"]

    async def create_habit(self, habit: HabitCreate) -> HabitRead:
        print("habit method called")
        doc = habit.dict()
        result = await self._habits.insert_one(doc)
        habit_id = str(result.inserted_id)
        return HabitRead(id=habit_id, **doc)

    async def list_habits(self) -> List[HabitRead]:
        cursor = self._habits.find({})
        habits: List[HabitRead] = []
        async for doc in cursor:
            doc_id = str(doc.get("_id"))
            habits.append(
                HabitRead(
                    id=doc_id,
                    name=doc["name"],
                    time_block=doc["time_block"],
                    target_minutes=doc["target_minutes"],
                )
            )
        return habits

    async def get_habit(self, habit_id: str) -> Optional[HabitRead]:
        doc = await self._habits.find_one({"_id": ObjectId(habit_id)})
        if not doc:
            return None
        return HabitRead(
            id=str(doc["_id"]),
            name=doc["name"],
            time_block=doc["time_block"],
            target_minutes=doc["target_minutes"],
        )

    async def record_progress(self, progress: ProgressCreate) -> ProgressRead:
        habit = await self.get_habit(progress.habit_id)
        if not habit:
            raise ValueError(f"Habit with id {progress.habit_id} not found")
        doc = {
            "habit_id": ObjectId(progress.habit_id),
            "date": progress.date.isoformat(),
            "minutes": progress.minutes,
        }
        await self._progress.update_one(
            {"habit_id": doc["habit_id"], "date": doc["date"]},
            {"$set": doc},
            upsert=True,
        )
        completed = progress.minutes >= habit.target_minutes
        return ProgressRead(
            habit_id=progress.habit_id,
            date=progress.date,
            minutes=progress.minutes,
            completed=completed,
        )

    async def get_progress_for_date(self, date: date) -> List[ProgressRead]:
        iso = date.isoformat()
        cursor = self._progress.find({"date": iso})
        results: List[ProgressRead] = []
        async for doc in cursor:
            habit_id = str(doc["habit_id"])
            habit = await self.get_habit(habit_id)
            completed = doc["minutes"] >= (habit.target_minutes if habit else 0)
            results.append(
                ProgressRead(
                    habit_id=habit_id,
                    date=date,
                    minutes=doc["minutes"],
                    completed=completed,
                )
            )
        return results

    async def compute_progress_bars(self, date: date) -> List[ProgressBar]:
        habits = await self.list_habits()
        bars: List[ProgressBar] = []
        for habit in habits:
            record = await self._progress.find_one(
                {"habit_id": ObjectId(habit.id), "date": date.isoformat()}
            )
            minutes = record["minutes"] if record else 0
            ratio = min(minutes / habit.target_minutes, 1.0)
            bars.append(ProgressBar(habit_id=habit.id, progress_ratio=ratio))
        return bars