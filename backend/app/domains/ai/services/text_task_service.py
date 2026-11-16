from typing import Any

from loguru import logger

from app.domains.ai.prompts import (
    CLASSIFY_SYSTEM,
    SUMMARY_SYSTEM,
    TITLE_SYSTEM,
    classify_prompt,
    summary_prompt,
    title_prompt,
)
from app.domains.ai.services.openrouter_client import AIErrorCode, AIProviderError, ChatResult, OpenRouterClient
from app.domains.ai.utils.model_output import (
    ClassificationResult,
    clean_title,
    parse_classification,
    transcript_excerpt,
)

MAX_TAGS = 5
# Summaries see the whole transcript up to this size (~100k tokens); longer ones keep their head and tail.
SUMMARY_TRANSCRIPT_LIMIT = 400_000
# Budgets cover the model's reasoning as well as the answer: reasoning models (DeepSeek Flash reasons at high effort
# by default) spend output tokens thinking first. Only tokens actually produced are billed.
SUMMARY_MAX_TOKENS = 32_000
TITLE_MAX_TOKENS = 4096
CLASSIFY_MAX_TOKENS = 4096
# OpenRouter's unified switch: answer without reasoning (every effort list in the catalog has `none`).
NO_REASONING = {'effort': 'none'}


class TextTaskService:
    """Text-model tasks on a finished transcript: title, tags + project suggestion (one JSON call), summaries."""

    def __init__(self, client: OpenRouterClient, model: str):
        self.client = client
        self.model = model

    async def _chat(self, messages: list[dict[str, Any]], **options: Any) -> ChatResult:
        """
        One text request that does not come back empty-handed because the model thought too long: when the answer
        is empty or cut off (a reasoning model can spend the whole budget on reasoning), ask once more with
        reasoning off. A model that refuses that option (HTTP 400) keeps its first answer.
        """
        result = await self.client.chat(model=self.model, messages=messages, **options)
        if result.text.strip() and result.finish_reason != 'length':
            return result
        logger.info(
            'Model {} answered {} (finish_reason={}, usage={}); retrying without reasoning',
            self.model,
            'nothing' if not result.text.strip() else 'a cut-off text',
            result.finish_reason,
            result.usage,
        )
        try:
            return await self.client.chat(model=self.model, messages=messages, reasoning=NO_REASONING, **options)
        except AIProviderError as error:
            if error.code != AIErrorCode.BAD_REQUEST:
                raise
            return result

    async def generate_title(self, transcript: str) -> str | None:
        if not transcript.strip():
            return None
        result = await self._chat(
            [
                {'role': 'system', 'content': TITLE_SYSTEM},
                {'role': 'user', 'content': title_prompt(transcript_excerpt(transcript, 12000))},
            ],
            max_tokens=TITLE_MAX_TOKENS,
            temperature=0.2,
            timeout=90.0,
        )
        return clean_title(result.text)

    async def classify(
        self, transcript: str, existing_tags: list[str], projects: list[str], *, max_tags: int = MAX_TAGS
    ) -> ClassificationResult:
        """Tags (existing names reused case-insensitively) and a project from `projects` when the model is confident."""
        if not transcript.strip():
            return ClassificationResult()
        messages = [
            {'role': 'system', 'content': CLASSIFY_SYSTEM},
            {
                'role': 'user',
                'content': classify_prompt(transcript_excerpt(transcript), existing_tags, projects, max_tags),
            },
        ]
        try:
            result = await self._chat(
                messages, max_tokens=CLASSIFY_MAX_TOKENS, temperature=0, json_mode=True, timeout=90.0
            )
        except AIProviderError as error:
            if error.code != AIErrorCode.BAD_REQUEST:
                raise
            # Not every model supports `response_format`; the parser copes with plain text.
            logger.info('JSON mode rejected by {}, retrying without it', self.model)
            result = await self._chat(messages, max_tokens=CLASSIFY_MAX_TOKENS, temperature=0, timeout=90.0)
        return parse_classification(result.text, existing_tags, projects, max_tags=max_tags)

    async def summarize(self, transcript: str, instruction: str, *, title: str | None = None) -> str:
        """Markdown result of `instruction` over the transcript. Raises `AIProviderError` on an empty/cut-off answer."""
        result = await self._chat(
            [
                {'role': 'system', 'content': SUMMARY_SYSTEM},
                {
                    'role': 'user',
                    'content': summary_prompt(
                        instruction, transcript_excerpt(transcript, SUMMARY_TRANSCRIPT_LIMIT), title
                    ),
                },
            ],
            max_tokens=SUMMARY_MAX_TOKENS,
            temperature=0.3,
            timeout=300.0,
        )
        text = result.text.strip()
        if not text:
            raise AIProviderError(AIErrorCode.EMPTY)
        if result.finish_reason == 'length':
            raise AIProviderError(AIErrorCode.INCOMPLETE)
        return text
