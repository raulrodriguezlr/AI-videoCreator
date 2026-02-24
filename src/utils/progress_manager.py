"""
progress_manager.py — Persistencia de progreso de generación de vídeo.

Guarda el estado de cada episodio (escenas completadas, fallidas, paths de clips)
para poder resumir la generación donde se quedó si algo falla.

Cada llamada a Veo es oro — NUNCA se pierde un clip generado.
"""

import os
import json
import time
from typing import Dict, Any, List, Optional
from datetime import datetime


class ProgressManager:
    """Manages episode generation progress persistence."""

    def __init__(self, episode_dir: str):
        """
        Args:
            episode_dir: Directory where progress.json will be stored
        """
        self.episode_dir = episode_dir
        self.progress_file = os.path.join(episode_dir, "progress.json")
        os.makedirs(episode_dir, exist_ok=True)

    # ==========================================
    # CORE CRUD
    # ==========================================

    def create_progress(
        self,
        episode_id: str,
        topic: str,
        script: Dict[str, Any],
        total_scenes: int,
    ) -> Dict[str, Any]:
        """Create initial progress file for a new episode."""
        progress = {
            "episode_id": episode_id,
            "topic": topic,
            "title": script.get("title", "Untitled"),
            "status": "in_progress",
            "total_scenes": total_scenes,
            "completed_scenes": 0,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "resume_from_scene": 0,
            "scenes": [],
            "errors": [],
        }

        # Initialize scene slots
        scenes = script.get("scenes", [])
        for i, scene in enumerate(scenes):
            progress["scenes"].append({
                "scene_number": i + 1,
                "status": "pending",  # pending | completed | failed | skipped
                "clip_path": None,
                "prompt": scene.get("visual_prompt", "")[:100],
                "narrative_phase": scene.get("narrative_phase", "unknown"),
                "error": None,
                "generated_at": None,
                "api_key_used": None,
                "model_used": None,
                "duration_seconds": None,
            })

        self._save(progress)
        return progress

    def load_progress(self) -> Optional[Dict[str, Any]]:
        """Load existing progress from file."""
        if not os.path.exists(self.progress_file):
            return None
        try:
            with open(self.progress_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"[PROGRESS] ⚠️  Error leyendo progress.json: {e}")
            return None

    def _save(self, progress: Dict[str, Any]):
        """Save progress to disk."""
        progress["updated_at"] = datetime.now().isoformat()
        with open(self.progress_file, "w", encoding="utf-8") as f:
            json.dump(progress, f, indent=2, ensure_ascii=False)

    # ==========================================
    # SCENE UPDATES
    # ==========================================

    def mark_scene_completed(
        self,
        scene_index: int,
        clip_path: str,
        model_used: str = None,
        api_key_used: str = None,
        duration_seconds: float = None,
    ):
        """Mark a scene as successfully generated."""
        progress = self.load_progress()
        if not progress:
            return

        if scene_index < len(progress["scenes"]):
            scene = progress["scenes"][scene_index]
            scene["status"] = "completed"
            scene["clip_path"] = clip_path
            scene["generated_at"] = datetime.now().isoformat()
            scene["model_used"] = model_used
            scene["api_key_used"] = ""
            scene["duration_seconds"] = duration_seconds

            # Update counters
            progress["completed_scenes"] = sum(
                1 for s in progress["scenes"] if s["status"] == "completed"
            )
            progress["resume_from_scene"] = self._next_pending_scene(progress)

            self._save(progress)

    def mark_scene_failed(
        self,
        scene_index: int,
        error: str,
        is_rate_limit: bool = False,
    ):
        """Mark a scene as failed."""
        progress = self.load_progress()
        if not progress:
            return

        if scene_index < len(progress["scenes"]):
            scene = progress["scenes"][scene_index]
            scene["status"] = "failed"
            scene["error"] = error

            # Log error with context
            progress["errors"].append({
                "scene_number": scene_index + 1,
                "error": error,
                "is_rate_limit": is_rate_limit,
                "timestamp": datetime.now().isoformat(),
            })

            progress["resume_from_scene"] = self._next_pending_scene(progress)

            # If rate limit, mark all remaining as pending and stop
            if is_rate_limit:
                progress["status"] = "paused_rate_limit"

            self._save(progress)

    def mark_scene_skipped(self, scene_index: int, reason: str = ""):
        """Mark a scene as skipped (e.g., user chose to skip)."""
        progress = self.load_progress()
        if not progress:
            return

        if scene_index < len(progress["scenes"]):
            progress["scenes"][scene_index]["status"] = "skipped"
            progress["scenes"][scene_index]["error"] = f"Skipped: {reason}"
            progress["resume_from_scene"] = self._next_pending_scene(progress)
            self._save(progress)

    def mark_episode_completed(self, final_video_path: str = None):
        """Mark entire episode as completed."""
        progress = self.load_progress()
        if not progress:
            return

        progress["status"] = "completed"
        progress["completed_at"] = datetime.now().isoformat()
        if final_video_path:
            progress["final_video_path"] = final_video_path

        self._save(progress)

    def mark_episode_failed(self, error: str):
        """Mark episode as failed (non-recoverable error)."""
        progress = self.load_progress()
        if not progress:
            return

        progress["status"] = "failed"
        progress["final_error"] = error
        self._save(progress)

    # ==========================================
    # QUERIES
    # ==========================================

    def get_completed_clips(self) -> List[Dict[str, Any]]:
        """Get all successfully generated clips."""
        progress = self.load_progress()
        if not progress:
            return []

        return [
            s for s in progress["scenes"]
            if s["status"] == "completed" and s.get("clip_path")
        ]

    def get_resume_index(self) -> int:
        """Get the scene index to resume from."""
        progress = self.load_progress()
        if not progress:
            return 0
        return progress.get("resume_from_scene", 0)

    def is_complete(self) -> bool:
        """Check if all scenes are done."""
        progress = self.load_progress()
        if not progress:
            return False
        return progress.get("status") == "completed"

    def get_status_summary(self) -> str:
        """Get a human-readable status summary."""
        progress = self.load_progress()
        if not progress:
            return "No progress found."

        total = progress["total_scenes"]
        completed = sum(1 for s in progress["scenes"] if s["status"] == "completed")
        failed = sum(1 for s in progress["scenes"] if s["status"] == "failed")
        pending = sum(1 for s in progress["scenes"] if s["status"] == "pending")

        lines = [
            f"📊 Episode: {progress['title']}",
            f"   Status: {progress['status']}",
            f"   Scenes: {completed}/{total} completed, {failed} failed, {pending} pending",
        ]

        if progress.get("resume_from_scene", 0) > 0:
            lines.append(f"   Resume from: scene {progress['resume_from_scene'] + 1}")

        if progress.get("errors"):
            last_error = progress["errors"][-1]
            lines.append(f"   Last error: {last_error['error'][:80]}")

        return "\n".join(lines)

    # ==========================================
    # HELPERS
    # ==========================================

    def _next_pending_scene(self, progress: Dict) -> int:
        """Find the index of the next pending or failed scene."""
        for i, scene in enumerate(progress["scenes"]):
            if scene["status"] in ("pending", "failed"):
                return i
        return progress["total_scenes"]  # All done


def is_rate_limit_error(error: Exception) -> bool:
    """Check if an exception is a rate limit error (429)."""
    error_str = str(error)
    return any(indicator in error_str for indicator in [
        "429",
        "RATE_LIMIT",
        "RESOURCE_EXHAUSTED",
        "quota",
        "Too Many Requests",
    ])


def is_content_error(error: Exception) -> bool:
    """Check if an exception is a content/safety error (not retryable)."""
    error_str = str(error)
    return any(indicator in error_str for indicator in [
        "SAFETY",
        "BLOCKED",
        "content policy",
        "harmful",
    ])
