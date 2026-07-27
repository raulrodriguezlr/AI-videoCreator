"""Higgsfield AI — SDK adapter driven by the official `hf` CLI.

Why the CLI and not REST? Higgsfield has TWO separate credit wallets:
  • the developer REST API key (platform.higgsfield.ai) → its OWN balance, which
    is empty for a plain Plus subscriber (submit → 403 "not_enough_credits");
  • the web/OAuth session → the user's PLUS SUBSCRIPTION credits (the 1000/mo they
    already pay for).
The official CLI (`@higgsfield/cli`, `hf auth login` device-code OAuth) uses the
SECOND wallet, so generations spend the plan credits the user owns. That is the
only first-party way to spend subscription credits programmatically.

────────────────────────────────────────────────────────────────────────────
CONTRACT BLOCK — the ONE place to edit if the CLI surface changes.
Verified against `@higgsfield/cli` v0.2.x (github.com/higgsfield-ai/cli):
  • Auth (once, by the user): `hf auth login`            → spends PLUS credits
  • Generate: `hf generate create <job_set_type> --prompt "..." [flags] --json --wait`
  • Flags: --aspect_ratio R · --duration N · --start-image PATH · --video PATH
           --wait (block, print result) · --wait-timeout 10m · --json (machine output)
  • --video PATH drives video_to_video EDITING models (e.g. Gemini Omni Flash,
    `cli_type: gemini_omni`) — the model keeps the original footage and applies
    the prompt as an edit, instead of generating from scratch. For a model that
    declares `video_to_video`, an `input_video` wins over `input_image` if both
    are present (see `_build_args`).
  • `--json --wait` prints a JSON job with the finished media at `result_url`
    (tolerant dig below also accepts results[].url / url / video_url).
  • Model id ⇒ `job_set_type` comes from each ModelSpec's `cli_type`.
  • Param handling: --duration is snapped to the model's `valid_durations`/
    `max_duration_s` (see `_snap_duration`) so we never send an unsupported clip
    length. The CLI exposes NO --resolution, seed or negative-prompt flag, so those
    fields are intentionally dropped (a CLI limitation, not an omission).
The binary is resolved from Settings.higgsfield_cli_path (default "hf" on PATH).
────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from videocreator.infrastructure.providers.sdk.adapter_base import (
    AdapterBase,
    GenRequest,
    GenResult,
)
from videocreator.shared.config import get_settings
from videocreator.shared.errors import HiggsfieldNeedsAuthError, ProviderError
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

# ---- CONTRACT BLOCK --------------------------------------------------------
#: Result locations to try in the CLI's `--json` output, best-known first.
_URL_PATHS: tuple[tuple[Any, ...], ...] = (
    ("result_url",),
    ("results", 0, "url"),
    ("results", 0, "result_url"),
    ("result", "url"),
    ("video_url",), ("image_url",), ("url",),
    ("assets", 0, "url"), ("jobs", 0, "results", "raw", "url"),
)
# ----------------------------------------------------------------------------


def _dig(obj: Any, path: tuple[Any, ...]) -> Any:
    cur = obj
    for step in path:
        try:
            cur = cur[step] if isinstance(step, int) else cur.get(step)  # type: ignore[union-attr]
        except (KeyError, IndexError, TypeError, AttributeError):
            return None
        if cur is None:
            return None
    return cur


def _first_url(data: Any) -> str | None:
    for path in _URL_PATHS:
        val = _dig(data, path)
        if isinstance(val, str) and val.startswith("http"):
            return val
    # last resort: any http string anywhere in the structure
    return _scan_url(data)


def _scan_url(obj: Any) -> str | None:
    if isinstance(obj, str):
        return obj if obj.startswith("http") and any(
            obj.lower().endswith(e)
            for e in (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".webm")
        ) else None
    if isinstance(obj, dict):
        for v in obj.values():
            u = _scan_url(v)
            if u:
                return u
    if isinstance(obj, list):
        for v in obj:
            u = _scan_url(v)
            if u:
                return u
    return None


def _parse_json(stdout: str) -> Any:
    """Parse the CLI's JSON output, tolerating progress lines before it."""
    s = stdout.strip()
    if not s:
        raise ProviderError("higgsfield CLI returned empty output")
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    # Fall back to the last JSON-parseable line (progress may precede the result).
    for raw_line in reversed(s.splitlines()):
        line = raw_line.strip()
        if line.startswith("{") or line.startswith("["):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    raise ProviderError(f"higgsfield CLI output was not JSON: {s[:200]}")


def _aspect_ratio(width: int, height: int) -> str:
    if height > width:
        return "9:16"
    if width > height:
        return "16:9"
    return "1:1"


def _snap_duration(seconds: float, model: Any) -> int:
    """Clamp to the model's max and snap to its discrete valid durations.

    The model only accepts certain clip lengths (Veo → 4/6/8). Sending an
    unsupported value (e.g. 5 or 7) can fail the job, so snap to the nearest
    allowed value (ties → longer). Without a `valid_durations` list, just clamp
    to `max_duration_s` and round.
    """
    max_s = int(getattr(model, "max_duration_s", 0) or 0)
    valid = tuple(getattr(model, "valid_durations", ()) or ())
    s = float(seconds)
    if max_s:
        s = min(s, max_s)
    if valid:
        allowed = [v for v in valid if not max_s or v <= max_s] or list(valid)
        return min(allowed, key=lambda v: (abs(v - s), -v))
    snapped = round(s) or 1
    return min(snapped, max_s) if max_s else snapped


class Adapter(AdapterBase):
    def _cli_path(self) -> str:
        return get_settings().higgsfield_cli_path or "hf"

    def _resolve_model(self, model_id: str | None) -> Any:
        if model_id:
            for m in self.manifest.models:
                if m.id == model_id:
                    return m
        # default: first model that has a CLI mapping
        for m in self.manifest.models:
            if getattr(m, "cli_type", ""):
                return m
        return self.manifest.models[0] if self.manifest.models else None

    def _build_args(self, request: GenRequest, model: Any, cli_type: str) -> list[str]:
        caps = list(getattr(model, "capabilities", []))
        is_image = caps == ["text_to_image"]
        timeout_s = int(self.manifest.latency.timeout_s or 600)
        args = [
            self._cli_path(), "generate", "create", cli_type,
            "--prompt", request.prompt,
            "--json", "--wait", "--wait-timeout", f"{timeout_s}s",
        ]
        ar = _aspect_ratio(request.width, request.height)
        if is_image:
            if ar != "1:1":
                args += ["--aspect_ratio", ar]
        else:
            args += [
                "--aspect_ratio", ar,
                "--duration", str(_snap_duration(request.duration_s, model)),
            ]
            video = request.extra.get("input_video")
            start = request.extra.get("input_image") or request.extra.get("image_url")
            # A model that declares video_to_video prefers the real clip over a
            # still frame when both are supplied; otherwise fall back to
            # whichever one is actually present.
            if video and ("video_to_video" in caps or not start):
                args += ["--video", str(video)]
            elif start:
                args += ["--start-image", str(start)]
        soul_id = request.extra.get("soul_id")
        if soul_id:
            args += ["--soul-id", str(soul_id)]
        return args

    async def generate(self, request: GenRequest) -> GenResult:
        model = self._resolve_model(request.model_id)
        cli_type = getattr(model, "cli_type", "") if model else ""
        if not cli_type:
            raise ProviderError(
                f"higgsfield: model '{request.model_id}' has no `cli_type` mapping "
                "(cannot drive it through the hf CLI)"
            )
        args = self._build_args(request, model, cli_type)
        is_image = list(getattr(model, "capabilities", [])) == ["text_to_image"]
        log.info("higgsfield.cli.run", cli_type=cli_type, prompt_len=len(request.prompt))

        stdout, stderr, code = await self._run(args)
        if code != 0:
            err_text = (stderr or stdout)[:600].lower()
            auth_hints = (
                "not authenticated", "unauthenticated", "please log in",
                "login required", "hf auth login", "auth login",
                "unauthorized", "session expired", "need to authenticate",
                "please authenticate", "you are not logged",
            )
            if any(h in err_text for h in auth_hints):
                raise HiggsfieldNeedsAuthError(
                    "higgsfield CLI requires auth — run `hf auth login` to authenticate "
                    "with your Plus subscription"
                )
            raise ProviderError(
                f"higgsfield CLI `{cli_type}` failed (exit {code}): {stderr[:300] or stdout[:300]}"
            )
        data = _parse_json(stdout)
        url = _first_url(data)
        if not url:
            raise ProviderError(
                f"higgsfield CLI `{cli_type}` finished without a media URL "
                f"(output keys={list(data) if isinstance(data, dict) else type(data)})"
            )
        media = await self._download(url)
        if not media:
            raise ProviderError("higgsfield CLI media download produced no bytes")

        w, h = (1080, 1920) if request.height > request.width else (1920, 1080)
        log.info("higgsfield.cli.done", cli_type=cli_type, size=len(media))
        return GenResult(
            video_bytes=media,
            duration_s=request.duration_s,
            width=w,
            height=h,
            model_id=getattr(model, "id", cli_type),
            seed=request.seed,
            has_audio=not is_image,
            metadata={"provider": "higgsfield", "cli_type": cli_type,
                      "transport": "cli", "source_url": url},
        )

    async def _run(self, args: list[str]) -> tuple[str, str, int]:
        """Run the hf CLI, returning (stdout, stderr, returncode)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise ProviderError(
                f"higgsfield CLI not found at '{args[0]}' — install `@higgsfield/cli` "
                "and run `hf auth login`, or set Settings.higgsfield_cli_path"
            ) from exc
        out, err = await proc.communicate()
        return (out.decode("utf-8", "replace"), err.decode("utf-8", "replace"),
                proc.returncode or 0)

    async def _download(self, url: str) -> bytes:
        try:
            import httpx
        except ImportError as e:  # pragma: no cover
            raise ProviderError("httpx not installed") from e
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code >= 400:
                raise ProviderError(f"higgsfield media download failed ({resp.status_code})")
            return resp.content

    async def health(self) -> dict[str, Any]:
        return {"available": True, "name": self.manifest.name, "transport": "cli"}
