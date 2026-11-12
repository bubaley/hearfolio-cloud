"""Fake OpenRouter for tests: a scripted `httpx2.MockTransport` that records requests. No network."""

import json
from collections.abc import Callable
from typing import Any

import httpx2

Reply = httpx2.Response | Callable[[httpx2.Request], httpx2.Response]


def chat_reply(text: str, finish_reason: str | None = 'stop', status: int = 200) -> httpx2.Response:
    return httpx2.Response(
        status,
        json={'model': 'test/model', 'choices': [{'message': {'content': text}, 'finish_reason': finish_reason}]},
    )


def error_reply(status: int, message: str = 'error', headers: dict[str, str] | None = None) -> httpx2.Response:
    return httpx2.Response(status, json={'error': {'code': status, 'message': message}}, headers=headers)


class FakeProvider:
    """Replies in order per path (`/chat/completions`, `/models`, …); the last reply repeats once the script ends."""

    def __init__(self, routes: dict[str, list[Reply]] | None = None):
        self.routes: dict[str, list[Reply]] = routes or {}
        self.requests: list[httpx2.Request] = []

    def add(self, path: str, *replies: Reply) -> FakeProvider:
        self.routes.setdefault(path, []).extend(replies)
        return self

    def calls(self, path: str) -> list[httpx2.Request]:
        return [request for request in self.requests if request.url.path.endswith(path)]

    def bodies(self, path: str) -> list[dict[str, Any]]:
        return [json.loads(request.content) for request in self.calls(path)]

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        for path, replies in self.routes.items():
            if request.url.path.endswith(path) and replies:
                reply = replies.pop(0) if len(replies) > 1 else replies[0]
                return reply if isinstance(reply, httpx2.Response) else reply(request)
        return httpx2.Response(404, json={'error': {'code': 404, 'message': 'not found'}})

    @property
    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handler)


async def no_sleep(_: float) -> None:
    return None
