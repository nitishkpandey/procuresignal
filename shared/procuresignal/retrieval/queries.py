"""Query groups and search terms for retrieval."""

QUERY_GROUPS = {
    "supplier_risk": [
        "supplier bankruptcy",
        "manufacturing facility shutdown",
        "M&A acquisition",
        "labor strike supplier",
        "quality issue recall",
    ],
    "logistics_disruption": [
        "port strike",
        "logistics disruption",
        "supply chain delay",
        "transportation crisis",
    ],
    "tariff_changes": [
        "tariff increase",
        "trade sanctions",
        "export restrictions",
        "trade agreement",
    ],
    "commodity_prices": [
        "steel price",
        "copper price",
        "aluminum price",
        "raw material shortage",
    ],
    "regulatory": [
        "CBAM regulation",
        "REACH compliance",
        "supply chain due diligence",
        "environmental regulation",
    ],
    "regional": [
        "supply chain Germany",
        "manufacturing Poland",
        "industrial Czech Republic",
        "automotive Mexico",
    ],
}


def get_queries_for_providers(provider_name: str) -> list[str]:
    """Get appropriate queries for a specific provider.

    Args:
        provider_name: "newsapi", "gdelt", or "rss"

    Returns:
        List of search queries
    """
    all_queries = []
    for group, queries in QUERY_GROUPS.items():
        all_queries.extend(queries)

    # NewsAPI limits to 100 req/day, so be selective
    if provider_name == "newsapi":
        return all_queries[:5]  # Just top 5 queries

    # GDELT and RSS are unlimited
    return all_queries
