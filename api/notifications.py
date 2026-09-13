from firebase_admin import firestore

from _common import body, db, json_error, now, require_user, response


def handler(event):
    try:
        user = require_user(event)
        collection = db().collection("notifications")
        if event.get("httpMethod", "GET") == "GET":
            records = collection.where("recipientId", "==", user["uid"]).limit(50).stream()
            items = [{"id": item.id, **item.to_dict()} for item in records]
            items.sort(key=lambda item: str(item.get("createdAt", "")), reverse=True)
            return response({"notifications": items})
        payload = body(event)
        if payload.get("action") == "mark-read":
            notification_id = str(payload.get("notificationId", ""))
            if not notification_id:
                return response({"error": "A notification is required."}, 422)
            notification = collection.document(notification_id).get()
            if not notification.exists or notification.to_dict().get("recipientId") != user["uid"]:
                return response({"error": "Notification not found."}, 404)
            collection.document(notification_id).update({"read": True, "readAt": now()})
            return response({"ok": True})
        return response({"error": "Unknown notification action."}, 400)
    except Exception as exc:
        return json_error(exc)
