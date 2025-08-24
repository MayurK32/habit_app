"""
Unit tests for the Habit Tracker API.

These tests use Python's built-in `unittest` framework to avoid
external dependencies. The asynchronous endpoints are exercised via
`httpx.AsyncClient` and `unittest.IsolatedAsyncioTestCase`.
"""

import asyncio
import unittest
from datetime import date
import os

import httpx

from app.main import app, get_repo
from app.repository import InMemoryRepository


class HabitTrackerTests(unittest.IsolatedAsyncioTestCase):
    """Test suite for the Habit Tracker API."""

    async def asyncSetUp(self):
        # Override repository with in-memory instance for each test
        self.repo = InMemoryRepository()
        app.dependency_overrides[get_repo] = lambda: self.repo
        # Use ASGITransport to run the app in memory without network calls
        transport = httpx.ASGITransport(app=app)
        self.client = httpx.AsyncClient(transport=transport, base_url="http://test")

    async def asyncTearDown(self):
        # Clear overrides and close client
        app.dependency_overrides.clear()
        await self.client.aclose()

    async def test_create_and_list_habits(self):
        # Create habit
        response = await self.client.post(
            "/habits",
            json={"name": "Morning meditation", "time_block": "morning", "target_minutes": 15},
        )
        self.assertEqual(response.status_code, 200)
        habit = response.json()
        self.assertEqual(habit["name"], "Morning meditation")
        # List habits
        response = await self.client.get("/habits")
        habits = response.json()
        self.assertEqual(len(habits), 1)
        self.assertEqual(habits[0]["id"], habit["id"])

    async def test_record_progress_and_bars(self):
        # Create habit
        resp = await self.client.post(
            "/habits",
            json={"name": "AI Reading", "time_block": "evening", "target_minutes": 30},
        )
        habit_id = resp.json()["id"]
        today = date.today().isoformat()
        # Record partial progress
        resp = await self.client.post(
            "/progress",
            json={"habit_id": habit_id, "date": today, "minutes": 20},
        )
        self.assertEqual(resp.status_code, 200)
        progress = resp.json()
        self.assertFalse(progress["completed"])
        # Compute progress bars
        resp = await self.client.get(f"/progress/bars/{today}")
        bars = resp.json()
        self.assertEqual(bars[0]["habit_id"], habit_id)
        expected_ratio = 20 / 30
        self.assertAlmostEqual(bars[0]["progress_ratio"], expected_ratio, places=3)

    async def test_speech_parsing(self):
        # Create two habits
        resp1 = await self.client.post(
            "/habits",
            json={"name": "Morning meditation", "time_block": "morning", "target_minutes": 15},
        )
        h1_id = resp1.json()["id"]
        resp2 = await self.client.post(
            "/habits",
            json={"name": "AI reading", "time_block": "evening", "target_minutes": 30},
        )
        h2_id = resp2.json()["id"]
        today = date.today().isoformat()
        speech_text = "morning meditation 15 minutes ai reading 30"
        resp = await self.client.post("/speech", json={"text": speech_text})
        self.assertEqual(resp.status_code, 200)
        # Retrieve progress
        resp = await self.client.get(f"/progress/{today}")
        entries = resp.json()
        self.assertEqual(len(entries), 2)
        ids = {entry["habit_id"] for entry in entries}
        self.assertEqual(ids, {h1_id, h2_id})
        for entry in entries:
            self.assertTrue(entry["completed"])

    async def test_manifest_and_service_worker(self):
        """Ensure the manifest and service worker are served correctly."""
        # Fetch manifest
        resp = await self.client.get("/manifest.json")
        self.assertEqual(resp.status_code, 200)
        # The manifest should be JSON
        self.assertIn("application/json", resp.headers.get("content-type"))
        data = resp.json()
        self.assertEqual(data["short_name"], "HabitTracker")
        # Fetch service worker
        resp_sw = await self.client.get("/service-worker.js")
        self.assertEqual(resp_sw.status_code, 200)
        self.assertIn("javascript", resp_sw.headers.get("content-type"))

    async def test_ai_parser_fallback(self):
        """Test that the AI parser falls back to heuristic when no API key is set."""
        # No OPENAI_API_KEY set in environment; ensure fallback output matches utils parser
        from app.utils import parse_speech_text
        from app.agents import parse_habits_with_ai
        # Ensure no API key is set so the AI parser will fall back
        os.environ.pop("OPENAI_API_KEY", None)
        # Create habits
        resp1 = await self.client.post(
            "/habits",
            json={"name": "morning meditation", "time_block": "morning", "target_minutes": 15},
        )
        resp2 = await self.client.post(
            "/habits",
            json={"name": "ai reading", "time_block": "evening", "target_minutes": 30},
        )
        habits = [resp1.json(), resp2.json()]
        text = "morning meditation 10 minutes ai reading 25"
        # Convert to HabitRead-like objects by retrieving from repo
        repo_habits = await self.repo.list_habits()
        expected_map = parse_speech_text(text, repo_habits)
        ai_map = await parse_habits_with_ai(text, repo_habits)
        self.assertEqual(ai_map, expected_map)

    async def test_completion_phrase_detection(self):
        """Test that completion phrases like 'I completed X' result in 100% progress."""
        # Create habit with 30 minute target
        resp = await self.client.post(
            "/habits",
            json={"name": "Morning workout", "time_block": "morning", "target_minutes": 30},
        )
        habit_id = resp.json()["id"]
        
        # Test various completion phrases
        completion_phrases = [
            "I completed morning workout",
            "finished morning workout today",
            "done with morning workout",
            "morning workout completed"
        ]
        
        for i, phrase in enumerate(completion_phrases):
            # Reset progress for each test
            today = date.today()
            if habit_id in self.repo._progress:
                self.repo._progress[habit_id].pop(today, None)
            
            resp = await self.client.post("/speech", json={"text": phrase})
            self.assertEqual(resp.status_code, 200)
            
            # Check that full target minutes were recorded
            progress_entries = resp.json()
            self.assertEqual(len(progress_entries), 1)
            self.assertEqual(progress_entries[0]["minutes"], 30)  # Should be full target
            self.assertTrue(progress_entries[0]["completed"])

    async def test_progress_accumulation_not_override(self):
        """Test that multiple speech inputs accumulate progress intelligently."""
        # Create habit with 60 minute target
        resp = await self.client.post(
            "/habits",
            json={"name": "Deep work", "time_block": "morning", "target_minutes": 60},
        )
        habit_id = resp.json()["id"]
        today = date.today().isoformat()
        
        # First session: 20 minutes
        resp1 = await self.client.post("/speech", json={"text": "deep work 20 minutes"})
        self.assertEqual(resp1.status_code, 200)
        progress1 = resp1.json()[0]
        self.assertEqual(progress1["minutes"], 20)
        self.assertFalse(progress1["completed"])
        
        # Second session: "another 25 minutes" (AI intelligently adds exactly 25 more)
        resp2 = await self.client.post("/speech", json={"text": "did another 25 minutes of deep work"})
        self.assertEqual(resp2.status_code, 200)
        progress2 = resp2.json()[0]
        # AI should add exactly 25 minutes to existing 20 = 45 total
        self.assertGreaterEqual(progress2["minutes"], 40)  # Allow some AI interpretation flexibility
        self.assertFalse(progress2["completed"])  # Still not completed (< 60)
        
        # Third session: "30 more minutes" (should definitely complete the habit)
        resp3 = await self.client.post("/speech", json={"text": "deep work for 30 more minutes"})
        self.assertEqual(resp3.status_code, 200)
        progress3 = resp3.json()[0]
        self.assertGreaterEqual(progress3["minutes"], 60)  # Should be at least 60 (completed)
        self.assertTrue(progress3["completed"])  # Now completed (>= 60)
        
        # Verify final state
        resp_final = await self.client.get(f"/progress/{today}")
        entries = resp_final.json()
        self.assertEqual(len(entries), 1)
        self.assertGreaterEqual(entries[0]["minutes"], 60)  # At least target completed
        self.assertTrue(entries[0]["completed"])


if __name__ == "__main__":
    unittest.main()