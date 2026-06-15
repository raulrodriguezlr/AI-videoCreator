"""Higgsfield character-anchor client — bind a local character to a reusable
Higgsfield identity so the same face/look can be reused across generations.

────────────────────────────────────────────────────────────────────────────
CONTRACT BLOCK — the ONE place to edit when the live REST contract is verified.

VERIFIED (via the Higgsfield MCP, 2026-06, Plus plan): the reusable-identity
primitive is an **Element** — created from 1+ reference images (+ optional name),
returns an `id`, and is referenced inside a prompt as `<<<id>>>`. (A heavier
**Soul** primitive also exists: 5-20 images, ~10 min training, used only with
Soul V2 / Cinema.) Elements are the instant, multi-model anchor we map to.

NOT YET VERIFIED: the *direct REST* endpoints the backend would call for
(a) uploading local image bytes to a Higgsfield media origin, and (b) creating
an Element from those media ids. The MCP performs these, but the underlying
HTTP routes are undocumented. Until confirmed they are gated behind
`_ELEMENTS_VERIFIED = False`, so this client NEVER fabricates a success — it
fails soft with a clear, actionable message and the caller leaves the character
un-anchored. Flip the flag and fill `_create_element_http` once verified.
────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

from dataclasses import dataclass

from videocreator.shared.config import Settings
from videocreator.shared.errors import ProviderError
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

#: Flip to True only when `_create_element_http` is implemented against the
#: confirmed live REST contract. Keeps speculative calls from running blind.
_ELEMENTS_VERIFIED = False


@dataclass(frozen=True)
class AnchorResult:
    """Outcome of an anchor sync — `ref_id` is None when nothing was created."""

    ref_id: str | None
    kind: str | None  # "element" | "soul"
    synced: bool
    detail: str


class HiggsfieldAnchorClient:
    """Create/lookup reusable Higgsfield identities for local characters."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def available(self) -> bool:
        """True only if credentials exist AND the REST contract is verified."""
        return bool(self._settings.higgsfield_credentials) and _ELEMENTS_VERIFIED

    async def create_element(self, *, name: str, image_urls: list[str]) -> AnchorResult:
        """Anchor `name` from `image_urls` as a Higgsfield Element.

        Fails soft: when not configured/verified it returns an un-synced
        `AnchorResult` with a reason instead of raising, so the UI can show
        status without the request 500-ing.
        """
        if not self._settings.higgsfield_credentials:
            return AnchorResult(
                None, None, False,
                "higgsfield_credentials not set — add KEY_ID:KEY_SECRET to use anchors",
            )
        if not image_urls:
            return AnchorResult(None, None, False, "character has no reference images to anchor")
        if not _ELEMENTS_VERIFIED:
            return AnchorResult(
                None, None, False,
                "Higgsfield Element REST contract not yet verified live — anchor "
                "is staged, not sent (see CONTRACT BLOCK in higgsfield_anchor.py)",
            )
        # Verified path — single seam to implement once the contract is confirmed.
        ref_id = await self._create_element_http(name=name, image_urls=image_urls)
        log.info("higgsfield.anchor.created", name=name, ref_id=ref_id)
        return AnchorResult(ref_id, "element", True, "anchored as Higgsfield element")

    async def _create_element_http(self, *, name: str, image_urls: list[str]) -> str:
        # Implement against the confirmed REST routes (media upload + element
        # create). Until then this must not be reached (guarded by the flag).
        raise ProviderError("Higgsfield Element create is not implemented yet")


__all__ = ["AnchorResult", "HiggsfieldAnchorClient"]
