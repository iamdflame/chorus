"""Test instruments.

`CountingLlm` is a measuring device, not a product mock. It exists to answer a question
the real Gemini cannot answer cheaply or exactly: *how many times did the model layer
actually get reached?* Proving that an unperturbed replay costs zero model calls requires
counting invocations at the model boundary, and a real API gives you a bill, not an
assertion.

It is confined to tests. The fleet, the API and the demo all run against real
`gemini-3.5-flash`, and `scripts/verify_determinism.py` runs the identical proof against
the live model.

Its outputs are a deterministic function of the request, which is what makes it a valid
instrument here: perturbing an input genuinely changes its output, so the causal cascade
under test is real rather than staged.
"""

from __future__ import annotations

import json
from typing import AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from kernel.effect import digest
from kernel.interposer import canonical_llm_request


class CountingLlm(BaseLlm):
    """A deterministic model that records how often it was actually invoked."""

    model: str = "counting-instrument"
    calls: int = 0
    seen: list[str] = []
    # When set, emit a function call to this tool before answering.
    use_tool: str | None = None
    tool_args: dict = {}

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.calls += 1
        fingerprint = digest(json.dumps(canonical_llm_request(llm_request), sort_keys=True))
        self.seen.append(fingerprint)

        already_used_tool = any(
            part.function_response is not None
            for content in (llm_request.contents or [])
            for part in (content.parts or [])
        )

        if self.use_tool and not already_used_tool:
            part = types.Part(
                function_call=types.FunctionCall(name=self.use_tool, args=dict(self.tool_args))
            )
        else:
            # Output depends on the request, so a perturbation upstream produces a
            # genuinely different answer and the causal cascade under test is real.
            part = types.Part(text=f"answer:{fingerprint[:12]}")

        yield LlmResponse(
            content=types.Content(role="model", parts=[part]),
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=100, candidates_token_count=20
            ),
        )

    def reset(self) -> None:
        self.calls = 0
        self.seen = []
