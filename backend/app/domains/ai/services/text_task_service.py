from loguru import logger

from app.domains.ai.prompts import (
    CLASSIFY_SYSTEM,
    SUMMARY_SYSTEM,
    TITLE_SYSTEM,
    classify_prompt,
    summary_prompt,
    title_prompt,
)
from app.domains.ai.services.openrouter_client import AIErrorCode, AIProviderError, OpenRouterClient
from app.domains.ai.utils.model_output import (
    ClassificationResult,
    clean_title,
    parse_classification,
    transcript_excerpt,
)

MAX_TAGS = 5
# Summaries see the whole transcript up to this size (~100k tokens); longer ones keep their head and tail.
SUMMARY_TRANSCRIPT_LIMIT = 400_000
SUMMARY_MAX_TOKENS = 8000


class TextTaskService:
    """Text-model tasks on a finished transcript: title, tags + project suggestion (one JSON call), summaries."""

    def __init__(self, client: OpenRouterClient, model: str):
        self.client = client
        self.model = model

    async def generate_title(self, transcript: str) -> str | None:
        if not transcript.strip():
            return None
        result = await self.client.chat(
            model=self.model,
            messages=[
                {'role': 'system', 'content': TITLE_SYSTEM},
                {'role': 'user', 'content': title_prompt(transcript_excerpt(transcript, 12000))},
            ],
            max_tokens=1024,
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
            result = await self.client.chat(
                model=self.model, messages=messages, max_tokens=2048, temperature=0, json_mode=True, timeout=90.0
            )
        except AIProviderError as error:
            if error.code != AIErrorCode.BAD_REQUEST:
                raise
            # Not every model supports `response_format`; the parser copes with plain text.
            logger.info('JSON mode rejected by {}, retrying without it', self.model)
            result = await self.client.chat(
                model=self.model, messages=messages, max_tokens=2048, temperature=0, timeout=90.0
            )
        return parse_classification(result.text, existing_tags, projects, max_tags=max_tags)

    async def summarize(self, transcript: str, instruction: str, *, title: str | None = None) -> str:
        """Markdown result of `instruction` over the transcript. Raises `AIProviderError` on an empty/cut-off answer."""
        result = await self.client.chat(
            model=self.model,
            messages=[
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
