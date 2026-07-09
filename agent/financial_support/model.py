"""Model factory: route Gemini 3.x to the Vertex ``global`` endpoint.

Gemini 3.x publisher models resolve only on the Vertex ``global`` endpoint,
while the platform services this demo uses (Agent Engine, the Evaluation
Service, BigQuery) stay **regional** via ``GOOGLE_CLOUD_LOCATION``. ADK's
documented way to split the two is to subclass :class:`~google.adk.models.Gemini`
and override ``api_client`` with a client pinned to ``location="global"``.

For 2.x models we return the plain model string so ADK uses the regional client
built from the environment — no override needed.
"""

from __future__ import annotations

from functools import cached_property

from google.adk.models import Gemini
from google.genai import Client

from .config import get_settings

# Publisher-model families that only resolve on the Vertex global endpoint.
_GLOBAL_ONLY_PREFIXES = ("gemini-3",)


class _GlobalGemini(Gemini):
    """A Gemini model whose API calls go to the global endpoint.

    Only the *model* endpoint is global; project + platform services stay on the
    regional location configured elsewhere.
    """

    @cached_property
    def api_client(self) -> Client:  # type: ignore[override]
        settings = get_settings()
        return Client(
            vertexai=True,
            project=settings.project,
            location="global",
        )


def build_model() -> str | Gemini:
    """Return the model spec for an ``LlmAgent``.

    A :class:`_GlobalGemini` instance for global-only families (Gemini 3.x), or
    the plain model string for regional models (Gemini 2.x).
    """

    settings = get_settings()
    if settings.model.startswith(_GLOBAL_ONLY_PREFIXES):
        return _GlobalGemini(model=settings.model)
    return settings.model
