import os

from _common import expire_subscriptions, response


def handler(event):
    headers = event.get("headers") or {}
    authorization = next((value for key, value in headers.items() if key.lower() == "authorization"), "")
    expected = os.environ.get("CRON_SECRET", "")
    if not expected or authorization != f"Bearer {expected}":
        return response({"error": "Unauthorized"}, 401)
    expired = expire_subscriptions()
    return response({"ok": True, "expired": expired})