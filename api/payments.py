import base64
import os
import uuid

import cloudinary
import cloudinary.uploader
from firebase_admin import firestore

from _common import PLANS, body, db, json_error, now, require_admin, require_user, response


def _notify(recipient_id, title, message, kind):
    db().collection("notifications").add({"recipientId": recipient_id, "title": title, "message": message, "kind": kind, "read": False, "createdAt": now()})


def _clear_rejection_notifications(recipient_id):
    collection = db().collection("notifications")
    for item in collection.where("recipientId", "==", recipient_id).stream():
        if item.to_dict().get("kind") == "payment-rejected":
            collection.document(item.id).delete()


def _cloudinary_setup():
    cloudinary.config(cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"], api_key=os.environ["CLOUDINARY_API_KEY"], api_secret=os.environ["CLOUDINARY_API_SECRET"], secure=True)


def handler(event):
    try:
        method = event.get("httpMethod", "GET")
        if method == "GET":
            user = require_user(event)
            records = db().collection("paymentRequests").where("userId", "==", user["uid"]).stream()
            payments = [{"id": item.id, **item.to_dict()} for item in records]
            payments.sort(key=lambda item: str(item.get("createdAt", "")), reverse=True)
            return response({"payments": payments})
        payload = body(event)
        action = payload.get("action")
        if action == "create":
            user = require_user(event)
            plan = PLANS.get(payload.get("planId"))
            if not plan:
                return response({"error": "Select a valid plan."}, 422)
            pending = db().collection("paymentRequests").where("userId", "==", user["uid"]).where("status", "==", "pending").limit(1).stream()
            if next(pending, None):
                return response({"error": "You already have a payment request awaiting review."}, 409)
            payment_id = uuid.uuid4().hex
            db().collection("paymentRequests").document(payment_id).set({
                "requestId": payment_id, "userId": user["uid"], "userName": user.get("name", "Student"), "userEmail": user.get("email", ""),
                "planId": payload["planId"], "planName": plan["name"], "amount": plan["amount"], "duration": plan["duration"],
                "status": "pending", "receiptUrl": "", "receiptPublicId": "", "rejectionReason": "", "createdAt": now(),
            })
            admins = db().collection("users").where("role", "==", "admin").stream()
            for admin_record in admins:
                _notify(admin_record.id, "Pending subscription", f"{user.get('name', 'A user')} submitted a subscription for review.", "payment-pending")
            return response({"id": payment_id}, 201)
        if action == "submit-proof":
            user = require_user(event)
            payment_ref = db().collection("paymentRequests").document(payload.get("paymentId", ""))
            payment = payment_ref.get()
            if not payment.exists or payment.to_dict().get("userId") != user["uid"]:
                return response({"error": "Payment request not found."}, 404)
            data = payment.to_dict()
            if data.get("status") != "pending":
                return response({"error": "This payment request is no longer awaiting proof."}, 409)
            if not payload.get("honest") or not payload.get("receiptData", "").startswith("data:"):
                return response({"error": "A genuine receipt and confirmation are required."}, 422)
            _cloudinary_setup()
            uploaded = cloudinary.uploader.upload(payload["receiptData"], folder=os.environ.get("CLOUDINARY_FOLDER", "cbt-receipts"), resource_type="auto", type="authenticated", public_id=f"{user['uid']}-{payment.id}")
            payment_ref.update({"receiptUrl": uploaded["secure_url"], "receiptPublicId": uploaded["public_id"], "submittedAt": now()})
            return response({"ok": True})
        admin = require_admin(event)
        if action == "admin-list":
            records = db().collection("paymentRequests").order_by("createdAt", direction=firestore.Query.DESCENDING).limit(100).stream()
            return response({"payments": [{"id": item.id, **item.to_dict()} for item in records]})
        if action == "review":
            payment_ref = db().collection("paymentRequests").document(payload.get("paymentId", ""))
            payment = payment_ref.get()
            if not payment.exists:
                return response({"error": "Payment not found."}, 404)
            update = {"reviewedBy": admin["uid"], "reviewedAt": now()}
            if payload.get("decision") == "approve":
                update.update({"status": "approved", "subscriptionStatus": "approved_pending_activation", "approvedAmount": payment.to_dict().get("amount", 0)})
                message = "Congratulations, your subscription was approved. Go to your dashboard to start using it."
            elif payload.get("decision") == "reject" and payload.get("reason", "").strip():
                update.update({"status": "rejected", "rejectionReason": payload["reason"].strip()})
                message = f"Your subscription was denied. Reason: {payload['reason'].strip()}"
            else:
                return response({"error": "A rejection reason is required."}, 422)
            payment_ref.update(update)
            recipient_id = payment.to_dict().get("userId")
            if payload.get("decision") == "approve":
                _clear_rejection_notifications(recipient_id)
            _notify(recipient_id, "Subscription update", message, "payment-approved" if payload.get("decision") == "approve" else "payment-rejected")
            return response({"ok": True})
        return response({"error": "Unknown payment action."}, 400)
    except Exception as exc:
        return json_error(exc)