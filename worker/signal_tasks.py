from __future__ import annotations

import logging

from procuresignal.signals.classifier import SignalClassifier
from procuresignal.signals.entity_resolver import EntityResolver
from procuresignal.signals.risk_scorer import RiskScorer

from worker.main import app

logger = logging.getLogger(__name__)


@app.task
def process_article_for_signals(article_id: str, article_text: str, headline: str):
    """Process an article to detect procurement signals.

    Runs a lightweight rule-based classifier, attempts entity resolution,
    computes an impact score, and persists detected signals via `_store_signal`.
    """
    try:
        classifier = SignalClassifier()
        signals = classifier.classify(article_text, headline)

        resolver = EntityResolver(db_session=None)
        scorer = RiskScorer()

        for signal in signals:
            logger.info("Detected %s signal in article %s", signal.signal_type, article_id)

            if signal.entity_name:
                resolved = resolver.resolve_company(signal.entity_name)
                if resolved:
                    signal.entity_id = resolved.entity_id
                    signal.entity_name = resolved.entity_name

            impact = scorer.score_signal(
                signal.signal_type.value, signal.severity.value, [signal.entity_name]
            )

            _store_signal(article_id, signal, impact)

        return {"signals_detected": len(signals), "article_id": article_id}

    except Exception as exc:  # pragma: no cover - runtime errors are propagated
        logger.exception("Error processing signals for article %s: %s", article_id, exc)
        raise


def _store_signal(article_id: str, signal, impact):
    """Persist the signal to the Signal table when DATABASE_URL is set.

    A no-op when DATABASE_URL is unset, so the worker can run without a DB
    (dev/test).
    """
    logger.debug("Storing signal for article %s: %s (impact=%s)", article_id, signal, impact)

    # Attempt to persist using DATABASE_URL if available. This makes the
    # worker behave gracefully when running without a DB (dev/test).
    import asyncio
    from os import getenv

    from procuresignal.config.database import session_scope

    database_url = getenv("DATABASE_URL")
    if not database_url:
        logger.debug("DATABASE_URL not set, skipping persistence of signal")
        return None

    # Lazy import of ORM models
    from procuresignal.models import Signal as SignalModel

    async def _do_store():
        async with session_scope(database_url) as session:
            model = SignalModel(
                signal_type=getattr(signal.signal_type, "value", str(signal.signal_type)),
                entity_id=signal.entity_id,
                article_id=article_id,
                confidence=getattr(signal, "confidence", None),
                severity=getattr(signal.severity, "value", str(signal.severity)),
                impact_areas=signal.impact_areas or [],
                raw_signal=signal.raw_data or {},
            )

            session.add(model)
            await session.commit()
            await session.refresh(model)

            logger.info("Stored signal id=%s for article=%s", model.id, article_id)
            return model.id

    try:
        return asyncio.get_event_loop().run_until_complete(_do_store())
    except RuntimeError:
        # If there's no running loop, create one
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_do_store())
        finally:
            loop.close()
