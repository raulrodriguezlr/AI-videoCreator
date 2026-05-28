"""
episode_manager.py — Gestión centralizada de episodios.

Cada episodio se almacena en su propia carpeta con estructura organizada:
    pods/<pod>/output/<episode_id>/
    ├── script.json          # Guión completo
    ├── progress.json        # Estado del progreso
    ├── clips/               # Clips de vídeo individuales
    │   ├── clip_01_establishing.mp4
    │   ├── clip_02_closeup.mp4
    │   └── ...
    └── final.mp4            # Vídeo concatenado

Uso:
    from src.utils.episode_manager import EpisodeManager
    em = EpisodeManager("pods/kids_story")
    episode = em.create_episode("Tico aprende paciencia", script)
    episodes = em.list_episodes()
"""

import os
import json
import re
from datetime import datetime
from typing import List, Dict, Any, Optional


class EpisodeManager:
    """Manages episode creation, listing, and organization for a pod."""

    def __init__(self, pod_dir: str):
        """
        Args:
            pod_dir: Path to the pod directory (e.g., "pods/kids_story").
        """
        self.pod_dir = pod_dir
        self.output_dir = os.path.join(pod_dir, "output")
        os.makedirs(self.output_dir, exist_ok=True)

    def create_episode(
        self,
        topic: str,
        script: dict,
    ) -> Dict[str, Any]:
        """
        Create a new episode directory with organized structure.

        Args:
            topic: Episode topic/title.
            script: Full script dict with scenes.

        Returns:
            Dict with episode_id, episode_dir, clips_dir, script_path.
        """
        episode_num = self._get_next_episode_number()
        safe_title = self._sanitize_title(topic)
        episode_id = f"ep_{episode_num:03d}_{safe_title}"
        episode_dir = os.path.join(self.output_dir, episode_id)
        clips_dir = os.path.join(episode_dir, "clips")

        # Create episode structure
        os.makedirs(episode_dir, exist_ok=True)
        os.makedirs(clips_dir, exist_ok=True)

        # Save script
        script_path = os.path.join(episode_dir, "script.json")
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(script, f, indent=2, ensure_ascii=False)

        # Save metadata
        metadata = {
            "episode_id": episode_id,
            "episode_number": episode_num,
            "topic": topic,
            "title": script.get("title", topic),
            "total_scenes": len(script.get("scenes", [])),
            "created_at": datetime.now().isoformat(),
            "status": "created",
        }
        metadata_path = os.path.join(episode_dir, "metadata.json")
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        print(f"[Episode] 📁 Episodio creado: {episode_id}")
        print(f"[Episode]    📄 Script: {script_path}")
        print(f"[Episode]    🎬 Clips: {clips_dir}")

        return {
            "episode_id": episode_id,
            "episode_dir": episode_dir,
            "clips_dir": clips_dir,
            "script_path": script_path,
        }

    def list_episodes(self) -> List[Dict[str, Any]]:
        """
        List all episodes in the pod with their status.

        Returns:
            List of episode info dicts, sorted by episode number.
        """
        episodes = []

        if not os.path.exists(self.output_dir):
            return episodes

        for name in sorted(os.listdir(self.output_dir)):
            ep_dir = os.path.join(self.output_dir, name)
            if not os.path.isdir(ep_dir) or not name.startswith("ep_"):
                continue

            episode_info = self._get_episode_info(ep_dir, name)
            episodes.append(episode_info)

        return episodes

    def get_episode(self, episode_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed info for a specific episode."""
        ep_dir = os.path.join(self.output_dir, episode_id)
        if not os.path.exists(ep_dir):
            return None
        return self._get_episode_info(ep_dir, episode_id)

    def get_clips(self, episode_id: str) -> List[Dict[str, Any]]:
        """
        List all clips for a specific episode.

        Returns:
            List of clip dicts with path, name, and size.
        """
        clips = []
        clips_dir = os.path.join(self.output_dir, episode_id, "clips")

        if not os.path.exists(clips_dir):
            # Fallback: check episode dir directly for legacy layout
            clips_dir = os.path.join(self.output_dir, episode_id)

        for name in sorted(os.listdir(clips_dir)):
            if name.endswith(".mp4") and name != f"{episode_id}.mp4" and name != "final.mp4":
                clip_path = os.path.join(clips_dir, name)
                clips.append({
                    "name": name,
                    "path": clip_path,
                    "size_mb": round(os.path.getsize(clip_path) / (1024 * 1024), 2),
                })

        return clips

    def get_clip_path(self, episode_dir: str, scene_index: int, narrative_phase: str = "") -> str:
        """
        Generate a standardized clip filename for a scene.

        Args:
            episode_dir: Path to the episode directory.
            scene_index: 0-based scene index.
            narrative_phase: Optional narrative phase (e.g., "establishing", "climax").

        Returns:
            Full path for the clip file.
        """
        clips_dir = os.path.join(episode_dir, "clips")
        os.makedirs(clips_dir, exist_ok=True)

        phase_suffix = f"_{narrative_phase}" if narrative_phase else ""
        filename = f"clip_{scene_index + 1:02d}{phase_suffix}.mp4"
        return os.path.join(clips_dir, filename)

    # ==========================================
    # INTERNAL HELPERS
    # ==========================================

    def _get_next_episode_number(self) -> int:
        """Get the next episode number based on existing episodes."""
        max_num = 0
        if os.path.exists(self.output_dir):
            for name in os.listdir(self.output_dir):
                if os.path.isdir(os.path.join(self.output_dir, name)):
                    match = re.match(r"ep_(\d+)", name)
                    if match:
                        max_num = max(max_num, int(match.group(1)))
        return max_num + 1

    def _sanitize_title(self, title: str) -> str:
        """Create a filesystem-safe title string."""
        safe = title[:30].strip()
        safe = re.sub(r"[^\w\s-]", "", safe)  # Remove special chars
        safe = re.sub(r"\s+", "_", safe)       # Spaces to underscores
        return safe.lower()

    def _get_episode_info(self, ep_dir: str, episode_id: str) -> Dict[str, Any]:
        """Build episode info dict from directory contents."""
        info = {
            "episode_id": episode_id,
            "dir": ep_dir,
            "status": "unknown",
            "clips_count": 0,
            "total_scenes": 0,
            "has_final": False,
        }

        # Load metadata if available
        metadata_path = os.path.join(ep_dir, "metadata.json")
        if os.path.exists(metadata_path):
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
            info.update({
                "title": metadata.get("title", ""),
                "topic": metadata.get("topic", ""),
                "total_scenes": metadata.get("total_scenes", 0),
                "created_at": metadata.get("created_at", ""),
            })

        # Load progress if available
        progress_path = os.path.join(ep_dir, "progress.json")
        if os.path.exists(progress_path):
            with open(progress_path, "r", encoding="utf-8") as f:
                progress = json.load(f)
            info["status"] = progress.get("status", "unknown")
            info["total_scenes"] = progress.get("total_scenes", info["total_scenes"])
            info["title"] = progress.get("title", info.get("title", ""))

        # Count clips
        clips_dir = os.path.join(ep_dir, "clips")
        if os.path.exists(clips_dir):
            info["clips_count"] = len([
                f for f in os.listdir(clips_dir)
                if f.endswith(".mp4")
            ])

        # Check for final video
        info["has_final"] = os.path.exists(os.path.join(ep_dir, f"{episode_id}.mp4")) or os.path.exists(os.path.join(ep_dir, "final.mp4"))

        # Derive status if not from progress
        if info["status"] == "unknown":
            if info["has_final"]:
                info["status"] = "completed"
            elif info["clips_count"] > 0:
                info["status"] = "in_progress"
            else:
                info["status"] = "created"

        return info

    def print_episodes_table(self):
        """Print a formatted table of all episodes."""
        episodes = self.list_episodes()

        if not episodes:
            print("  (sin episodios)")
            return

        status_icons = {
            "completed": "✅",
            "in_progress": "🔄",
            "created": "📝",
            "failed": "❌",
            "unknown": "❓",
        }

        for ep in episodes:
            icon = status_icons.get(ep["status"], "❓")
            title = ep.get("title", ep["episode_id"])[:40]
            clips = f"{ep['clips_count']}/{ep['total_scenes']}" if ep["total_scenes"] else str(ep["clips_count"])
            final = " 🎬" if ep["has_final"] else ""
            print(f"  {icon} {ep['episode_id']} — {title} ({clips} clips{final})")
