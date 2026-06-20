"""Verify the signals router is reachable from the canonical location."""

from api.routers.signals import router as signals_router


def test_signals_router_prefix_and_routes():
    assert signals_router.prefix == "/api/signals"
    paths = {route.path for route in signals_router.routes}
    assert "/api/signals/" in paths
    assert "/api/signals/stats/summary" in paths
