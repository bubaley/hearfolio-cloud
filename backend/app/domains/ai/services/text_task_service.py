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
# How hard a reasoning model may think (OpenRouter's unified `reasoning.effort`). Models such as DeepSeek Flash default
# to `high`, which is slow and wasteful here: a summary needs a little thought to pick what matters, a title or tags
# none. Models without reasoning ignore it; a model that rejects the value gets the request without it.
SUMMARY_REASONING = 'low'
SHORT_TASK_REASONING = 'none'


class TextTaskService:
    """Text-model tasks on a finished transcript: title, tags + project suggestion (one JSON call), summaries."""

    def __init__(self, client: OpenRouterClient, model: str):
        self.client = client
        self.model = model

    async def _ask(self, messages: list[dict[str, Any]], effort: str, **options: Any) -> ChatResult:
        """The request with `reasoning.effort`; without it when the model rejects the value (HTTP 400)."""
        try:
            return await self.client.chat(model=self.model, messages=messages, reasoning={'effort': effort}, **options)
        except AIProviderError as error:
            if error.code != AIErrorCode.BAD_REQUEST:
                raise
            logger.info('Model {} rejected reasoning effort {}, asking without it', self.model, effort)
            return await self.client.chat(model=self.model, messages=messages, **options)

    async def _chat(self, messages: list[dict[str, Any]], *, effort: str, **options: Any) -> ChatResult:
        """
        One text request at the given reasoning effort that does not come back empty-handed: when the answer is
        empty or cut off (a reasoning model can spend the whole budget thinking), ask once more with reasoning off.
        A model that refuses that option (HTTP 400) keeps its first answer.
        """
        result = await self._ask(messages, effort, **options)
        if effort == 'none' or (result.text.strip() and result.finish_reason != 'length'):
            return result
        logger.info(
            'Model {} answered {} (finish_reason={}, usage={}); retrying without reasoning',
            self.model,
            'nothing' if not result.text.strip() else 'a cut-off text',
            result.finish_reason,
            result.usage,
        )
        try:
            return await self.client.chat(model=self.model, messages=messages, reasoning={'effort': 'none'}, **options)
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
            effort=SHORT_TASK_REASONING,
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
                messages,
                effort=SHORT_TASK_REASONING,
                max_tokens=CLASSIFY_MAX_TOKENS,
                temperature=0,
                json_mode=True,
                timeout=90.0,
            )
        except AIProviderError as error:
            if error.code != AIErrorCode.BAD_REQUEST:
                raise
            # Not every model supports `response_format`; the parser copes with plain text.
            logger.info('JSON mode rejected by {}, retrying without it', self.model)
            result = await self._chat(
                messages, effort=SHORT_TASK_REASONING, max_tokens=CLASSIFY_MAX_TOKENS, temperature=0, timeout=90.0
            )
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
            effort=SUMMARY_REASONING,
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
