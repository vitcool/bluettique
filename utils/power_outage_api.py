import logging


def fetch_electricity_outages(*_args, **_kwargs):
    """Outage fetching is disabled; return an empty schedule."""
    logging.info("Outage schedule fetching disabled; returning empty schedule.")
    return []
