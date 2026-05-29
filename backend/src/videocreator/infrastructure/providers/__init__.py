"""Concrete video/voice provider adapters implementing domain ports.

Each adapter speaks one external API and maps it onto `VideoProviderPort` so the
application layer never learns which vendor (or which underlying model) produced
a clip.
"""
