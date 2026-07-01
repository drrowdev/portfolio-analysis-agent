"""Streaming AI chat endpoint grounded in full portfolio context."""

import asyncio
import logging
import queue
import threading
from typing import AsyncGenerator

import anthropic
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.services.analysis import (
    _get_portfolio_context,
    _get_strategy_context,
    _get_goals_context,
    _get_recent_news,
    SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

CHAT_SYSTEM_PROMPT = f"""You are a senior portfolio strategist chatting with an individual investor (Finnish tax rules apply).
You have access to their full portfolio data, investment strategy, goals, and recent market news.

{SYSTEM_PROMPT.split('RESPONSE FORMAT:')[0].strip()}

RESPONSE FORMAT: Respond in clear, well-structured prose (NOT JSON). Use markdown formatting.
- Show your math when doing calculations. The investor wants to verify your reasoning.
- Use actual numbers from the portfolio data — never approximate when exact figures are available.
- Tag recommendations with conviction level (HIGH/MEDIUM/LOW) when giving actionable advice.
- If asked about tax implications, always specify the account type and calculate the actual tax impact.
- Be direct. If asked "should I sell X?", give a clear yes/no with the rationale, not a list of pros and cons.
"""


class ChatRequest(BaseModel):
    message: str
    history: list[dict] | None = None


async def _build_full_context(db: AsyncSession) -> str:
    """Build comprehensive context from all portfolio data."""
    parts = []
    parts.append(await _get_portfolio_context(db))
    parts.append(await _get_strategy_context(db))
    parts.append(await _get_goals_context(db))
    parts.append(await _get_recent_news(db))

    # Add performance summary
    from app.services.portfolio import compute_performance_comparison
    try:
        perf = await compute_performance_comparison(db, "1y")
        if perf and perf.data:
            latest = perf.data[-1]
            parts.append(
                f"\nPERFORMANCE (1Y):\n"
                f"  Portfolio return: {latest.portfolio_return_pct:.1f}%\n"
                f"  S&P 500 return: {latest.sp500_return_pct:.1f}%"
            )
    except Exception:
        pass

    return "\n\n".join(parts)


_SENTINEL = object()


def _run_claude_stream(q: queue.Queue, messages: list[dict], system: str):
    """Run Claude streaming in a background thread, pushing chunks to a queue."""
    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        with client.messages.stream(
            model="claude-sonnet-5",
            max_tokens=20000,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            system=system,
            messages=messages,
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        q.put(event.delta.text)
    except Exception as e:
        q.put(e)
    finally:
        q.put(_SENTINEL)


async def _stream_chat(
    message: str, context: str, history: list[dict] | None = None,
) -> AsyncGenerator[str, None]:
    """Stream Claude response with keep-alive during thinking."""
    messages = []

    # Add conversation history
    if history:
        for msg in history[-10:]:
            messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
            })

    # Add current message with context
    user_content = f"""Here is my current portfolio data and context:

{context}

---

My question: {message}"""

    messages.append({"role": "user", "content": user_content})

    # Run Claude in a thread so we can send keep-alive bytes while it thinks
    q: queue.Queue = queue.Queue()
    thread = threading.Thread(
        target=_run_claude_stream, args=(q, messages, CHAT_SYSTEM_PROMPT), daemon=True
    )
    thread.start()

    while True:
        try:
            item = q.get(timeout=5)
        except queue.Empty:
            # No data in 5s — send a space to keep the connection alive
            yield " "
            continue

        if item is _SENTINEL:
            break
        if isinstance(item, Exception):
            yield f"\n\n⚠️ Error: {item}"
            break
        yield item


@router.post("/stream")
async def chat_stream(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    """Stream AI chat response grounded in portfolio data."""
    context = await _build_full_context(db)

    return StreamingResponse(
        _stream_chat(req.message, context, req.history),
        media_type="text/plain",
    )
