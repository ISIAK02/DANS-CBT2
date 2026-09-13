import json
import os
from datetime import datetime, timezone
from functools import lru_cache

import firebase_admin
from firebase_admin import auth, credentials, firestore


PLANS = {
    "day": {"name": "1 Day Access", "amount": 1000, "duration": 86400},
    "two-days": {"name": "2 Days Access", "amount": 2000, "duration": 172800},
    "week": {"name": "1 Week Special Promo", "amount": 5000, "duration": 604800},
    "super-premium": {"name": "Super Premium", "amount": 10000, "duration": None, "permanent": True},
}


@lru_cache(maxsize=1)
def db():
    if not firebase_admin._apps:
        private_key = os.environ.get("FIREBASE_PRIVATE_KEY", "").replace("\\n", "\n")
        firebase_admin.initialize_app(credentials.Certificate({
            "type": "service_account",
            "project_id": os.environ["FIREBASE_PROJECT_ID"],
            "private_key": private_key,
            "client_email": os.environ["FIREBASE_CLIENT_EMAIL"],
            "token_uri": "https://oauth2.googleapis.com/token",
        }))
    return firestore.client()


def response(payload, status=200):
    return {"statusCode": status, "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": os.environ.get("APP_ORIGIN", "*")}, "body": json.dumps(payload, default=str)}


def body(event):
    raw = event.get("body") or "{}"
    return json.loads(raw) if isinstance(raw, str) else raw


def bearer(event):
    headers = event.get("headers") or {}
    value = next((item for key, item in headers.items() if key.lower() == "authorization"), "")
    scheme, _, token = value.partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


def user_from_event(event):
    token = bearer(event)
    if not token:
        raise PermissionError("Authentication required")
    db()
    return auth.verify_id_token(token)


def require_user(event):
    try:
        user = user_from_event(event)
        if not user.get("email_verified"):
            raise PermissionError("Please verify your email address before continuing.")
        return user
    except Exception as exc:
        if isinstance(exc, PermissionError):
            raise
        raise PermissionError("Authentication required") from exc


def require_admin(event):
    user = require_user(event)
    snapshot = db().collection("users").document(user["uid"]).get()
    if not snapshot.exists or snapshot.to_dict().get("role") != "admin":
        raise PermissionError("Administrator access required")
    return user


def now():
    return datetime.now(timezone.utc)


def active_subscription(uid):
    records = db().collection("subscriptions").where("userId", "==", uid).where("status", "==", "active").limit(10).stream()
    current = now()
    for record in records:
        data = record.to_dict()
        end = data.get("subscriptionEnd")
        if data.get("permanent"):
            return record
        if end and end.timestamp() > current.timestamp():
            return record
        db().collection("subscriptions").document(record.id).update({"status": "expired"})
    return None


def json_error(exc):
    if isinstance(exc, PermissionError):
        return response({"error": str(exc)}, 403)
    return response({"error": "The request could not be completed."}, 400)