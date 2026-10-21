"""Thin OpenAI wrapper: one structured-output call. No knowledge of MCP or sources."""

from openai import AsyncOpenAI
from pydantic import BaseModel


class LLMClient:
    def __init__(self, api_key: str, model: str, timeout: float):
        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout, max_retries=2)
        self._model = model

    async def structured[T: BaseModel](self, system: str, user: str, schema: type[T]) -> T:
        """Return a validated instance of `schema` (OpenAI structured outputs)."""
        response = await self._client.chat.completions.parse(
            model=self._model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format=schema,
        )
        message = response.choices[0].message
        if message.parsed is None:
            raise RuntimeError(f"The model returned no {schema.__name__}: {message.refusal or 'empty response'}")
        return message.parsed
