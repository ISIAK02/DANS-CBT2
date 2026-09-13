from datetime import datetime, timedelta, timezone

from _common import PLANS, db, json_error, now, require_admin, response


def _day_start(days_ago=0):
    today = now().replace(hour=0, minute=0, second=0, microsecond=0)
    return today - timedelta(days=days_ago)


def _is_today(value):
    return value and value >= _day_start()


def _date_key(value):
    return value.astimezone(timezone.utc).strftime("%b %d") if value else ""


def _amount(item):
    value = item.get("approvedAmount", item.get("amount", 0))
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0


def handler(event):
    try:
        require_admin(event)
        users = [item.to_dict() for item in db().collection("users").stream()]
        attempts = [item.to_dict() for item in db().collection("examAttempts").stream()]
        payments = [item.to_dict() for item in db().collection("paymentRequests").stream()]
        subscriptions = [item.to_dict() for item in db().collection("subscriptions").stream()]
        submitted = [item for item in attempts if item.get("status") == "submitted"]
        approved = [item for item in payments if item.get("status") == "approved"]
        today_users = sum(1 for item in users if _is_today(item.get("createdAt")))
        today_exams = sum(1 for item in submitted if _is_today(item.get("submittedAt")))
        today_active_users = len({item.get("userId") for item in submitted if _is_today(item.get("submittedAt")) and item.get("userId")})
        today_approved = sum(1 for item in approved if _is_today(item.get("reviewedAt") or item.get("createdAt")))
        revenue = sum(_amount(item) for item in approved)
        today_revenue = sum(_amount(item) for item in approved if _is_today(item.get("reviewedAt")))
        active_subscriptions = sum(1 for item in subscriptions if item.get("status") == "active" and (item.get("permanent") or not item.get("subscriptionEnd") or item["subscriptionEnd"] > now()))
        average = round(sum(float(item.get("percentage", 0)) for item in submitted) / len(submitted), 1) if submitted else 0
        grades = {name: 0 for name in ("A", "B", "C", "D", "E", "F")}
        for item in submitted:
            grades[item.get("grade", "F")] = grades.get(item.get("grade", "F"), 0) + 1
        activity = []
        for days_ago in range(6, -1, -1):
            start = _day_start(days_ago)
            end = start + timedelta(days=1)
            activity.append({
                "label": _date_key(start),
                "users": sum(1 for item in users if start <= item.get("createdAt", datetime.min.replace(tzinfo=timezone.utc)) < end),
                "exams": sum(1 for item in submitted if start <= item.get("submittedAt", datetime.min.replace(tzinfo=timezone.utc)) < end),
            })
        return response({"analytics": {"todayUsers": today_users, "todayActiveUsers": today_active_users, "todayExams": today_exams, "todayApproved": today_approved, "totalApproved": len(approved), "todayRevenue": today_revenue, "revenue": revenue, "totalRevenue": revenue, "activeSubscriptions": active_subscriptions, "totalUsers": len(users), "totalExams": len(submitted), "averageScore": average, "passes": sum(1 for item in submitted if float(item.get("percentage", 0)) >= 50), "fails": sum(1 for item in submitted if float(item.get("percentage", 0)) < 50), "grades": grades, "activity": activity}})
    except Exception as exc:
        return json_error(exc)
