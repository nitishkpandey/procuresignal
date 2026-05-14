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

    This task currently runs a lightweight rule-based classifier,
    attempts entity resolution (if DB session is provided) and
    computes an impact score. Storage is left to integration with
    the project's ORM in `_store_signal`.
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
    """Persist the signal to the DB.

    This is intentionally left as a placeholder: projects should
    implement this to insert into their chosen ORM or database layer.
    """
    logger.debug("Storing signal for article %s: %s (impact=%s)", article_id, signal, impact)

    # Attempt to persist using DATABASE_URL if available. This makes the
    # worker behave gracefully when running without a DB (dev/test).
    import asyncio
    from os import getenv

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    database_url = getenv("DATABASE_URL")
    if not database_url:
        logger.debug("DATABASE_URL not set, skipping persistence of signal")
        return None

    # Lazy import of ORM models
    from shared.procuresignal.models import Signal as SignalModel

    async def _do_store():
        engine = create_async_engine(database_url, future=True)
        async_session = async_sessionmaker(engine, expire_on_commit=False)

        async with async_session() as session:
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
            await engine.dispose()
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
