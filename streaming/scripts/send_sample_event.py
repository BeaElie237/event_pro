"""Send a signed sample event to the ingestion webhook (stdlib only).

    python streaming/scripts/send_sample_event.py --url http://localhost:8001 --secret "$WEBHOOK_SECRET"
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import urllib.request
from datetime import date, timedelta

SAMPLE = {
    "source": "partner_demo",
    "source_event_id": "demo-001",
    "title": "Pan-African AI Hackathon — Fully Funded",
    "description": "48h hackathon on AI for agriculture and health. Travel and accommodation covered.",
    "url": "https://example.org/events/pan-african-ai-hackathon?utm_source=webhook",
    "start_date": (date.today() + timedelta(days=45)).isoformat(),
    "end_date": (date.today() + timedelta(days=47)).isoformat(),
    "deadline": (date.today() + timedelta(days=20)).isoformat(),
    "location": "Kigali, Rwanda",
    "organizer": "Demo Foundation",
    "tags": ["AI", "agritech", "health"],
    "language": "en",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8001")
    parser.add_argument("--secret", required=True)
    args = parser.parse_args()

    body = json.dumps(SAMPLE).encode()
    signature = "sha256=" + hmac.new(args.secret.encode(), body, hashlib.sha256).hexdigest()
    request = urllib.request.Request(
        f"{args.url.rstrip('/')}/webhooks/events",
        data=body,
        headers={"Content-Type": "application/json", "X-EventPro-Signature": signature},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        print(response.status, response.read().decode())


if __name__ == "__main__":
    main()
