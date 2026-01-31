import os
import json
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips
from typing import Dict, List
from src.variables import VIDEO_FPS, VIDEO_CODEC, AUDIO_CODEC

class VideoAssembler:
    def __init__(self, pod_config_path: str):
        self.config = self._load_config(pod_config_path)
        self.output_dir = os.path.join(os.path.dirname(pod_config_path), "output")
        os.makedirs(self.output_dir, exist_ok=True)

    def _load_config(self, path: str) -> dict:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def assemble_video(self, script: Dict, visual_paths: List[str], audio_paths: Dict[int, str]) -> str:
        """
        Assembles the video from visual and audio assets.
        Returns the path to the final video file.
        """
        print("--- Iniciando Ensamblaje de Video ---")
        clips = []
        
        for i, scene in enumerate(script['scenes']):
            image_path = visual_paths[i]
            audio_path = audio_paths.get(i)
            
            # Create Image Clip with Ken Burns Effect (Zoom In)
            # Duration will be determined by audio length or default estimate
            if audio_path and os.path.exists(audio_path):
                audio_clip = AudioFileClip(audio_path)
                duration = audio_clip.duration + 0.5 # Add padding
            else:
                audio_clip = None
                duration = scene.get('duration_est', 5)
            
            # Load image and resize to standard 720p to ensure consistency
            clip = ImageClip(image_path).set_duration(duration).resize(height=720)
            
            # Apply Ken Burns (Simple Zoom In)
            # We crop the center and slowly zoom in by resizing from 1.0 to 1.1x
            w, h = clip.size
            clip = clip.resize(lambda t: 1 + 0.05 * t)  # Zoom logic: 5% zoom per second aprox
            # Center crop to keep aspect ratio fixed (1280x720)
            clip = clip.set_position(('center', 'center')).set_duration(duration)
            # To make it work with CompositeVideoClip or write_videofile we usually need to composite it over a background 
            # or ensure the resize doesn't change canvas size weirdly. 
            # Simpler approach for MoviePy 1.x:
            # Just resize the clip dynamically. Note: This can be slow.
            
            if audio_clip:
                clip = clip.set_audio(audio_clip)
                
            clips.append(clip)
            print(f"Clip {i+1} preparado: {duration:.2f}s (con efecto Ken Burns)")

        # Concatenate all clips
        final_video = concatenate_videoclips(clips, method="compose")
        
        # Output filename
        episode_title = script.get('title', 'Untitled').replace(' ', '_')
        output_filename = f"{episode_title}.mp4"
        output_path = os.path.join(self.output_dir, output_filename)
        
        # Write file
        print(f"Renderizando video final en: {output_path}...")
        # Low fps for testing speed, codec for compatibility
        final_video.write_videofile(output_path, fps=VIDEO_FPS, codec=VIDEO_CODEC, audio_codec=AUDIO_CODEC)
        
        return output_path

if __name__ == "__main__":
    # Test execution
    assembler = VideoAssembler("pods/kids_story/config.json")
    print("VideoAssembler inicializado correctamente.")
