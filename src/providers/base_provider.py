"""
BaseVideoProvider — Abstract base class for all video generation providers.

Every provider must implement these atomic methods:
- generate_scene: Creates a single video clip from a text prompt.
- extend_scene: Extends an existing video clip by generating additional footage.
- jump_to_scene: Creates a new scene using the last frame of the previous clip as seed.
- generate_full_video: Orchestrates the full video generation from a script.
- check_availability: Verifies the provider is ready to use.
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any


class VideoClip:
    """Represents a generated video clip with its metadata."""

    def __init__(
        self,
        file_path: str,
        duration: float,
        seed: Optional[int] = None,
        operation_name: Optional[str] = None,
        video_ref: Any = None,
    ):
        self.file_path = file_path
        self.duration = duration
        self.seed = seed
        self.operation_name = operation_name
        self.video_ref = video_ref  # Provider-specific reference (e.g., Veo video object)


class BaseVideoProvider(ABC):
    """Abstract base for all video providers."""

    def __init__(self, pod_config_path: str):
        self.pod_config_path = pod_config_path

    @abstractmethod
    def generate_scene(
        self,
        prompt: str,
        duration: int = 8,
        seed: Optional[int] = None,
        reference_images: Optional[List[str]] = None,
        negative_prompt: Optional[str] = None,
    ) -> VideoClip:
        """
        Generate a single video clip from a text prompt.

        Args:
            prompt: Cinematographic text prompt for the scene.
            duration: Duration in seconds (4, 6, or 8 for Veo).
            seed: Optional seed for reproducibility.
            reference_images: Optional list of image paths for character consistency.
            negative_prompt: Things to avoid in the generation.

        Returns:
            VideoClip with the generated video file path and metadata.
        """
        pass

    @abstractmethod
    def extend_scene(
        self,
        video_clip: VideoClip,
        prompt: str,
    ) -> VideoClip:
        """
        Extend an existing video clip with additional footage.
        The extended footage continues the same scene seamlessly.

        Args:
            video_clip: The previous VideoClip to extend.
            prompt: Prompt describing what happens next in the same scene.

        Returns:
            VideoClip with the extended video (original + extension).
        """
        pass

    @abstractmethod
    def jump_to_scene(
        self,
        previous_clip: VideoClip,
        prompt: str,
        reference_images: Optional[List[str]] = None,
    ) -> VideoClip:
        """
        Create a new scene using the last frame of the previous clip as seed.
        This creates a "hard cut" to a new scene while maintaining visual consistency.

        Args:
            previous_clip: The previous VideoClip (last frame will be extracted).
            prompt: Prompt describing the new scene.
            reference_images: Optional reference images for consistency.

        Returns:
            VideoClip with the new scene.
        """
        pass

    @abstractmethod
    def generate_full_video(
        self,
        script: Dict[str, Any],
        output_path: str,
    ) -> str:
        """
        Orchestrate full video generation from a structured script.
        Uses Scene Builder logic: generate first scene, then chain
        extend/jump_to for subsequent scenes.

        Args:
            script: Full script dict with scenes, camera metadata, etc.
            output_path: Path where the final video will be saved.

        Returns:
            Path to the final assembled video file.
        """
        pass

    @abstractmethod
    def check_availability(self) -> bool:
        """
        Verify this provider is available and ready to use.

        Returns:
            True if the provider can generate videos, False otherwise.
        """
        pass
