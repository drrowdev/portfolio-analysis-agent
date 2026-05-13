"""Claude API analysis agent for portfolio insights.

Tax-aware, strategy-aware recommendations for an investor using Finnish brokerage accounts:
- Arvo-osuustili (AOT): standard 30/34% capital gains tax, tax-loss harvesting possible
- Osakesäästötili (OST): tax-deferred (€100k lifetime deposit cap), no taxable events inside
- ESPP (Fidelity): employer ESPP with qualifying/disqualifying disposition rules
"""

import json
import logging
from decimal import Decimal
from typing import Any

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.account import Account
from app.models.alert import AnalysisHistory, AnalysisType
from app.models.holding import Holding  # noqa: F401
from app.models.news import NewsArticle
from app.models.strategy import Strategy

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior portfolio strategist advising an individual investor (Finnish tax rules apply).
You combine quantitative analysis with practical judgment. You think in terms of risk-adjusted returns,
position sizing, and portfolio construction — not just individual stock picks.

ANALYTICAL FRAMEWORK — always follow this structure:
1. SITUATION: What does the data show? Cite specific numbers from the portfolio.
2. RISK ASSESSMENT: What could go wrong? Concentration risk, correlation, drawdowns, macro headwinds.
3. RECOMMENDATION: What specifically should be done, in what size, in which account, and over what timeframe?

POSITION SIZING PRINCIPLES:
- No single stock should exceed 30% of total portfolio unless it's an employer ESPP with holding period constraints.
- Correlated positions (e.g. multiple tech stocks) should be assessed as a group, not individually.
- New positions: start at 2-5% of portfolio; scale up only with conviction and time.
- Always state recommended position sizes as both € amounts and % of portfolio.

CONVICTION LEVELS — tag every recommendation:
- HIGH: Strong thesis, clear catalyst, act within days. Size: full target allocation.
- MEDIUM: Good thesis but uncertain timing. Size: half position now, reassess in 2-4 weeks.
- LOW: Monitoring/watchlist. Size: no action yet, set conditions for entry.

KEY TAX RULES (Finland):
- Arvo-osuustili (AOT): Capital gains taxed at 30% (≤€30k/year) or 34% (>€30k).
  Each sale is a taxable event. Tax-loss harvesting is beneficial.
  Dividends: Finnish listed 85% taxable, foreign 100% taxable minus withholding credits.
- Osakesäästötili (OST): Tax-deferred. No taxes on trades/dividends inside.
  Taxed ONLY on withdrawal (growth portion at 30/34%). Max lifetime DEPOSITS: €100,000.
  The €100k cap applies ONLY to cash deposited, NOT to account value — gains can grow unlimited.
  Check the portfolio context for current OST deposits — if at or near the €100k cap, NEVER suggest depositing more.
  Best for: high-growth and high-dividend stocks that benefit from tax-deferred compounding.
- ESPP (Fidelity): employer stock purchase plan.
  Qualifying disposition: held >2y from offering, >1y from purchase → favorable tax treatment.
  Track holding periods carefully before any sale recommendation.
- Crypto (Kraken): Capital gains taxed at 30/34%. FIFO cost basis. Each trade is taxable.
  Transfers between wallets are NOT taxable.

IMPORTANT CONSTRAINTS:
- Show your math. When recommending trades, include the calculation (e.g. "Selling 50 shares × €365 = €18,250").
- Never hallucinate data. Only reference numbers provided in the portfolio context.
- Be direct. If a position should be sold, say so clearly with the rationale. Don't hedge with "consider" when the data is clear.
- Distinguish between urgent actions and strategic adjustments. Not everything needs to happen today.

RESPONSE FORMAT: Always respond in valid JSON with this structure:
{
  "summary": "2-3 sentence executive overview with the single most important takeaway",
  "insights": [{"title": "...", "detail": "...", "severity": "info|warning|action", "sources": [{"name": "...", "url": "...", "date": "DD.MM.YYYY"}]}],
  "recommendations": [{"action": "...", "rationale": "...", "account_type": "...", "priority": "high|medium|low"}],
  "risk_factors": ["..."]
}

NOTE ON SOURCES: Include the "sources" array in insights ONLY when news articles are provided in the context.
For analysis types without news data (rebalance, tax optimization), omit the sources array or leave it empty.
"""


async def _get_portfolio_context(db: AsyncSession) -> str:
    """Build a text summary of the current portfolio for Claude."""
    stmt = select(Account).options(selectinload(Account.holdings))
    result = await db.execute(stmt)
    accounts = list(result.scalars().all())

    # Fetch cash available
    from app.models.user_settings import UserSetting
    cash_result = await db.execute(
        select(UserSetting).where(UserSetting.key == "cash_available")
    )
    cash_setting = cash_result.scalar_one_or_none()
    cash_available = Decimal(cash_setting.value) if cash_setting else Decimal("0")

    lines = ["CURRENT PORTFOLIO:"]
    total_value = Decimal("0")
    total_cost = Decimal("0")

    for account in accounts:
        lines.append(f"\n## {account.name} ({account.account_type.value}, {account.broker})")
        lines.append(f"   Tax treatment: {account.tax_treatment.value}")
        acct_value = Decimal("0")
        acct_cost = Decimal("0")

        for h in account.holdings:
            value = h.current_value_eur or h.total_cost_eur
            cost = h.total_cost_eur
            pnl = value - cost
            pnl_pct = (pnl / cost * 100) if cost else Decimal("0")
            lines.append(
                f"   {h.symbol}: {h.total_quantity} shares, "
                f"cost €{cost:.2f}, value €{value:.2f}, "
                f"P/L €{pnl:.2f} ({pnl_pct:.1f}%)"
            )
            acct_value += value
            acct_cost += cost

        lines.append(f"   Account total: €{acct_value:.2f} (cost €{acct_cost:.2f})")
        total_value += acct_value
        total_cost += acct_cost

    lines.append(
        f"\nCASH AVAILABLE TO INVEST: €{cash_available:.2f}"
    )
    lines.append(
        f"\nTOTAL PORTFOLIO (incl. cash): €{total_value + cash_available:.2f} "
        f"(invested €{total_cost:.2f}, P/L €{total_value - total_cost:.2f}, cash €{cash_available:.2f})"
    )
    return "\n".join(lines)


async def _get_strategy_context(db: AsyncSession) -> str:
    """Get the active investment strategy."""
    stmt = select(Strategy).where(Strategy.is_active == True)  # noqa: E712
    result = await db.execute(stmt)
    strategy = result.scalar_one_or_none()

    if not strategy:
        return "No investment strategy defined yet."

    lines = [
        f"INVESTMENT STRATEGY: {strategy.name}",
        f"Description: {strategy.description}",
        f"Risk tolerance: {strategy.risk_tolerance.value}",
        f"Target allocation: {json.dumps(strategy.target_allocation)}",
        f"Rebalance threshold: {strategy.rebalance_threshold_pct}%",
        f"Tax optimization: {'enabled' if strategy.tax_optimization_enabled else 'disabled'}",
    ]
    if strategy.custom_rules:
        lines.append(f"Custom rules: {json.dumps(strategy.custom_rules)}")
    return "\n".join(lines)


async def _get_recent_news(db: AsyncSession, limit: int = 30) -> str:
    """Get recent news articles as context, prioritizing most recent."""
    from datetime import datetime, timedelta

    # Fetch articles from the last 3 days, prioritizing the most recent
    cutoff = datetime.utcnow() - timedelta(days=3)
    stmt = (
        select(NewsArticle)
        .where(NewsArticle.published_at >= cutoff)
        .order_by(NewsArticle.published_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    articles = list(result.scalars().all())

    if not articles:
        return "No recent news available."

    lines = ["RECENT NEWS (sorted newest first — prioritize the most recent articles):"]
    for a in articles:
        sentiment = f" (sentiment: {a.sentiment_score})" if a.sentiment_score else ""
        source = a.source or "Unknown"
        url = a.url or ""
        lines.append(
            f"- [{a.symbol or 'MARKET'}] {a.title}{sentiment} "
            f"(source: {source}, date: {a.published_at.strftime('%d.%m.%Y')}, url: {url})"
        )
    return "\n".join(lines)


async def _get_goals_context(db: AsyncSession) -> str:
    """Get active investment goals with projections."""
    from app.models.goal import InvestmentGoal

    stmt = select(InvestmentGoal).where(InvestmentGoal.is_active == True)  # noqa: E712
    result = await db.execute(stmt)
    goals = list(result.scalars().all())

    if not goals:
        return "No investment goals defined."

    from datetime import date
    today = date.today()
    lines = ["INVESTMENT GOALS (informational context — do NOT let ambitious goals override sound risk management or strategy):"]
    for g in goals:
        months = max((g.target_date.year - today.year) * 12 + (g.target_date.month - today.month), 1)
        lines.append(
            f"- {g.name}: target €{g.target_amount_eur:,.0f} by {g.target_date} "
            f"({months} months remaining, assumed {g.assumed_annual_return_pct}% annual return)"
        )
        if g.notes:
            lines.append(f"  Notes: {g.notes}")
    return "\n".join(lines)


async def _call_claude(prompt: str) -> dict[str, Any]:
    """Call Claude API and parse JSON response."""
    if not settings.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set, returning mock analysis")
        return {
            "summary": "Analysis unavailable — Anthropic API key not configured.",
            "insights": [],
            "recommendations": [],
            "risk_factors": ["API key not configured"],
        }

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    message = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=16000,
        temperature=1,  # required for extended thinking
        thinking={
            "type": "enabled",
            "budget_tokens": 10000,
        },
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    # With extended thinking, response has thinking blocks + text blocks
    text = ""
    for block in message.content:
        if block.type == "text":
            text = block.text
            break
    # Handle markdown code blocks
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    return json.loads(text.strip())


async def _save_analysis(
    db: AsyncSession, analysis_type: AnalysisType, content: dict[str, Any]
) -> AnalysisHistory:
    """Persist analysis result to the database."""
    analysis = AnalysisHistory(analysis_type=analysis_type, content=content)
    db.add(analysis)
    await db.flush()
    await db.refresh(analysis)
    return analysis


async def daily_summary(db: AsyncSession) -> dict[str, Any]:
    """Generate a daily portfolio summary with insights."""
    # Refresh news first to ensure we have the latest articles
    from app.services.news_monitor import poll_all_news
    try:
        await poll_all_news(db)
        await db.flush()
    except Exception as e:
        logger.warning("News refresh failed before daily summary: %s", e)

    portfolio = await _get_portfolio_context(db)
    strategy = await _get_strategy_context(db)
    news = await _get_recent_news(db)

    from datetime import date as date_type
    today_str = date_type.today().strftime("%d.%m.%Y")

    prompt = f"""Provide a concise daily market briefing focused on NEWS AND EVENTS relevant to the stocks in this portfolio.

TODAY'S DATE: {today_str}

{portfolio}

{strategy}

{news}

RULES:
- Focus ONLY on what's happening in the market, industry, and companies — NOT on portfolio performance, P/L, or position sizes.
- Do NOT recommend buying, selling, or holding any stock. Do NOT flag declining positions or suggest exiting them.
- Do NOT mention portfolio value, unrealized gains/losses, or cost basis.
- PRIORITIZE THE MOST RECENT NEWS. Articles from today or yesterday are FAR more relevant than older ones. If earnings results, Fed decisions, or other major events have already happened (published today), report on the OUTCOMES — don't say they are "upcoming" or "imminent".
- If an event has already occurred (e.g., earnings reported, Fed decision announced), summarize the actual result and market reaction — not speculation about what might happen.
- Maximum 1-2 insights per stock. Only include a stock if there is genuinely new, material news or events since last market close.
- If a stock has no new developments, do NOT write an insight for it.
- Combine related macro/industry themes into a single insight rather than repeating per stock.
- Keep each insight to 1-2 sentences max.
- For "recommendations", list only upcoming catalysts, earnings dates, macro events, or things worth monitoring — NOT trade suggestions or portfolio actions.
- Keep "risk_factors" to 2-3 macro/geopolitical/industry risks currently in play.
- The "summary" should be 2 sentences max about the overall market/news environment.
- Prioritize quality over quantity — a briefing with 3 high-signal insights is better than 10 low-signal ones.
- Each insight MUST include a "sources" array citing the news articles used. Each source needs "name", "url", and "date" (DD.MM.YYYY). Only reference URLs from the provided RECENT NEWS — never invent URLs. Prefer sources dated today or yesterday over older ones.
"""

    result = await _call_claude(prompt)
    await _save_analysis(db, AnalysisType.daily_summary, result)
    return result


async def rebalance_recommendation(db: AsyncSession) -> dict[str, Any]:
    """Generate rebalancing recommendations."""
    portfolio = await _get_portfolio_context(db)
    strategy = await _get_strategy_context(db)
    goals = await _get_goals_context(db)

    prompt = f"""Conduct a full portfolio review and rebalancing analysis.

{portfolio}

{strategy}

{goals}

ANALYSIS STRUCTURE — follow this order:

1. PORTFOLIO HEALTH CHECK
   - Calculate current allocation percentages vs strategy targets. Show the gaps.
   - Identify concentration risks: any single position >25%? Any sector >50%?
   - Assess correlation: are multiple holdings exposed to the same risk factors?

2. CASH STRATEGY
   - Current cash: assess whether to deploy, hold, accumulate, or DCA.
   - If deploying: specify exact amounts and target positions.
   - If holding: state what conditions would trigger deployment (price levels, events, timeframe).
   - Consider: market valuation levels, upcoming catalysts (earnings, macro events), portfolio gaps.

3. SPECIFIC TRADE RECOMMENDATIONS
   - For each recommended action: state the exact trade (symbol, quantity, € amount, which account).
   - Include conviction level (HIGH/MEDIUM/LOW) and timeframe (immediate / within 2 weeks / within 1-3 months).
   - For sells: calculate the tax impact in AOT. Compare after-tax proceeds vs holding.
   - For buys: explain why this position size and why this account.

4. WHAT NOT TO DO
   - Explicitly state 1-2 things the investor might be tempted to do but shouldn't, and why.

5. NEXT REVIEW TRIGGERS
   - What events or price levels should prompt the next rebalance review?
"""

    result = await _call_claude(prompt)
    await _save_analysis(db, AnalysisType.rebalance, result)
    return result


async def tax_optimization_analysis(db: AsyncSession) -> dict[str, Any]:
    """Analyze tax optimization opportunities."""
    portfolio = await _get_portfolio_context(db)
    goals = await _get_goals_context(db)

    prompt = f"""Conduct a tax optimization review for this investor's portfolio (Finnish tax rules apply).

{portfolio}

{goals}

ANALYSIS STRUCTURE:

1. TAX-LOSS HARVESTING (AOT only)
   - Identify positions with unrealized losses. Calculate the tax savings from harvesting each.
   - Show the math: loss amount × 30% (or 34% if total gains >€30k) = tax saved.
   - Flag wash sale considerations if re-entering the position.

2. GAIN REALIZATION PLANNING
   - Estimate total realized gains this year (from data available). How close to the €30k threshold?
   - If under €30k: should gains be realized this year at 30% vs pushing to next year?
   - If over €30k: all additional gains taxed at 34% — does this change the sell/hold calculus?

3. ACCOUNT PLACEMENT OPTIMIZATION
   - Which current holdings would be better served in a different account (if movable)?
   - High-dividend stocks: quantify the dividend tax drag in AOT vs tax-free compounding in OST.
   - High-growth stocks: quantify the benefit of tax-deferred compounding in OST.

4. ESPP TAX TIMING
   - Identify MSFT lots approaching qualifying disposition dates.
   - Calculate the tax difference between qualifying and disqualifying disposition for actionable lots.

5. CRYPTO TAX CONSIDERATIONS
   - Any unrealized losses worth harvesting? FIFO impact on remaining cost basis.
   - Optimal timing for any planned trades.
"""

    result = await _call_claude(prompt)
    await _save_analysis(db, AnalysisType.tax_optimization, result)
    return result


async def news_impact_analysis(db: AsyncSession) -> dict[str, Any]:
    """Analyze the impact of recent news on portfolio."""
    portfolio = await _get_portfolio_context(db)
    news = await _get_recent_news(db, limit=30)
    strategy = await _get_strategy_context(db)
    goals = await _get_goals_context(db)

    prompt = f"""Analyze how recent news impacts this portfolio and recommend actions.

{portfolio}

{strategy}

{goals}

{news}

For each material news item affecting a portfolio holding:
1. IMPACT: Positive/negative/neutral on the specific holding. Quantify if possible (e.g. "could affect revenue by X%").
2. MATERIALITY: Is this a thesis-changer, a short-term catalyst, or noise? Be honest — most news is noise.
3. ACTION: Specific recommendation with conviction level (HIGH/MEDIUM/LOW).
   - If action required: state exact trade, account, and timing.
   - If no action: say "Hold — this is priced in" or "Monitor — reassess if X happens".
4. TAX CONTEXT: If selling is recommended, note the tax implications in the relevant account.
5. GOAL IMPACT: Does this news materially change the trajectory toward investment goals?

IMPORTANT: Filter aggressively. Only include news that genuinely affects the investment thesis.
Cite sources for every insight using the provided news URLs.
"""

    result = await _call_claude(prompt)
    await _save_analysis(db, AnalysisType.news_impact, result)
    return result
