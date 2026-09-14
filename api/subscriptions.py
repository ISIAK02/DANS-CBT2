from datetime import timedelta

from firebase_admin import firestore

from _common import PLANS, active_subscription, body, db, expire_subscriptions, json_error, now, require_user, response


def handler(event):
    try:
        user = require_user(event)
        if event.get("httpMethod", "GET") == "GET":
            expire_subscriptions(user["uid"])
            records = db().collection("subscriptions").where("userId", "==", user["uid"]).stream()
            subscriptions = []
            for item in records:
                data = item.to_dict()
                subscriptions.append({"id": item.id, **data})
            subscriptions.sort(key=lambda item: str(item.get("createdAt", "")), reverse=True)
            return response({"subscriptions": subscriptions[:10]})
        payload = body(event)
        if payload.get("action") == "start-demo":
            if active_subscription(user["uid"]):
                raise PermissionError("An active subscription is already available on this account.")
            demo_ref = db().collection("subscriptions").document(f"demo-{user['uid']}")
            transaction = db().transaction()

            @firestore.transactional
            def start_demo(transaction):
                existing = demo_ref.get(transaction=transaction)
                if existing.exists:
                    raise PermissionError("Your demo mode has already been used. Subscribe to continue using the CBT app.")
                start = now()
                end = start + timedelta(minutes=20)
                transaction.create(demo_ref, {
                    "userId": user["uid"],
                    "kind": "demo",
                    "planName": "20 Minute Demo",
                    "status": "active",
                    "activatedAt": start,
                    "subscriptionStart": start,
                    "subscriptionEnd": end,
                    "createdAt": start,
                })
                return {"subscriptionStart": start, "subscriptionEnd": end}

            result = start_demo(transaction)
            return response({"ok": True, **result}, 201)
        if payload.get("action") != "activate":
            return response({"error": "Unknown subscription action."}, 400)
        payment_ref = db().collection("paymentRequests").document(payload.get("paymentId", ""))
        subscription_ref = db().collection("subscriptions").document(payment_ref.id)
        transaction = db().transaction()

        @firestore.transactional
        def activate(transaction):
            payment = payment_ref.get(transaction=transaction)
            if not payment.exists or payment.to_dict().get("userId") != user["uid"]:
                raise PermissionError("Payment request not found.")
            data = payment.to_dict()
            plan = PLANS.get(data.get("planId"))
            if not plan or data.get("status") != "approved" or data.get("subscriptionStatus") != "approved_pending_activation":
                raise PermissionError("This payment is not ready for activation.")
            subscription = subscription_ref.get(transaction=transaction)
            if subscription.exists and subscription.to_dict().get("activatedAt"):
                raise PermissionError("This subscription has already been activated.")
            start = now()
            end = start + timedelta(seconds=plan["duration"]) if plan.get("duration") else None
            transaction.set(subscription_ref, {"userId": user["uid"], "paymentId": payment_ref.id, "planId": data["planId"], "planName": plan["name"], "status": "active", "permanent": plan.get("permanent", False), "activatedAt": start, "subscriptionStart": start, "subscriptionEnd": end, "createdAt": start})
            transaction.update(payment_ref, {"status": "active", "subscriptionStatus": "active", "activatedAt": start, "subscriptionStart": start, "subscriptionEnd": end})
            return {"subscriptionStart": start, "subscriptionEnd": end}

        result = activate(transaction)
        return response({"ok": True, **result})
    except Exception as exc:
        return json_error(exc)