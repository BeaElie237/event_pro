"""Shared domain logic for EventPro (batch, streaming and API layers).

A single source of truth for the event taxonomy, normalization rules and the
embedding text format guarantees that an event ingested by the Spark batch and
the same event received through the stream end up with the same fingerprint,
the same categories and comparable vectors.
"""

__version__ = "0.1.0"
