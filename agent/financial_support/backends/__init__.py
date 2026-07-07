"""Mock external systems (swappable). Real backends drop in behind these.

* :mod:`customer_db` — customer reads (BigQuery in production).
* :mod:`payment_processor` — money-moving refunds (external API in production).
* :mod:`faults` — deterministic fault injection ("feature flags") for the demo.
* :mod:`data` — seed fixtures.
"""
