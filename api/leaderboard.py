from _common import body, db, json_error, now, require_user, response, user_from_event


LEADERBOARD_COLLECTION = "leaderboard"
GRADE_NAMES = ("A", "B", "C", "D", "E", "F")


def grade_for(percentage):
    if percentage >= 80:
        return "A"
    if percentage >= 60:
        return "B"
    if percentage >= 50:
        return "C"
    if percentage >= 40:
        return "D"
    if percentage >= 30:
        return "E"
    return "F"


def _first_name(name, fallback="Student"):
    parts = str(name or "").strip().split()
    return parts[0][:40] if parts else fallback


def _public_entries():
    records = db().collection(LEADERBOARD_COLLECTION).where("optedIn", "==", True).stream()
    entries = [{"id": item.id, **item.to_dict()} for item in records]
    entries.sort(key=lambda item: (-item.get("perfectPercentage", item.get("perfectScores", 0)), -item.get("examsTaken", item.get("examsPassed", 0)), -item.get("passes", 0), -item.get("fails", 0), -item.get("bestScore", 0), str(item.get("updatedAt", ""))))
    return [{"displayName": item.get("displayName", "Student"), "profilePicture": item.get("profilePicture", ""), "perfectPercentage": item.get("perfectPercentage", item.get("perfectScores", 0)), "examsTaken": item.get("examsTaken", item.get("examsPassed", 0)), "passes": item.get("passes", 0), "fails": item.get("fails", 0), "bestScore": item.get("bestScore", 0), "grades": item.get("grades", {name: 0 for name in GRADE_NAMES})} for item in entries[:50]]


def _viewer(event):
    try:
        user = user_from_event(event)
    except PermissionError:
        return {"joined": False, "rank": None}
    record = db().collection(LEADERBOARD_COLLECTION).document(user["uid"]).get()
    if not record.exists or not record.to_dict().get("optedIn"):
        return {"joined": False, "rank": None}
    all_entries = db().collection(LEADERBOARD_COLLECTION).where("optedIn", "==", True).stream()
    ranked = [{"id": item.id, **item.to_dict()} for item in all_entries]
    ranked.sort(key=lambda item: (-item.get("perfectPercentage", item.get("perfectScores", 0)), -item.get("examsTaken", item.get("examsPassed", 0)), -item.get("passes", 0), -item.get("fails", 0), -item.get("bestScore", 0), str(item.get("updatedAt", ""))))
    rank = next((index + 1 for index, item in enumerate(ranked) if item["id"] == user["uid"]), None)
    return {"joined": True, "rank": rank}


def update_after_exam(user_id, percentage):
    user_snapshot = db().collection("users").document(user_id).get()
    user_data = user_snapshot.to_dict() if user_snapshot.exists else {}
    leaderboard_ref = db().collection(LEADERBOARD_COLLECTION).document(user_id)
    existing = leaderboard_ref.get()
    current = existing.to_dict() if existing.exists else {}
    grade = grade_for(percentage)
    grades = {name: int(current.get("grades", {}).get(name, 0)) for name in GRADE_NAMES}
    grades[grade] += 1
    exams_taken = int(current.get("examsTaken", current.get("examsPassed", 0))) + 1
    perfect_percentage = int(current.get("perfectPercentage", current.get("perfectScores", 0))) + (1 if percentage == 100 else 0)
    leaderboard_ref.set({
        "displayName": _first_name(user_data.get("name")),
        "profilePicture": user_data.get("profilePicture", ""),
        "perfectPercentage": perfect_percentage,
        "perfectScores": perfect_percentage,
        "examsTaken": exams_taken,
        "examsPassed": exams_taken,
        "passes": int(current.get("passes", 0)) + (1 if percentage >= 50 else 0),
        "fails": int(current.get("fails", 0)) + (1 if percentage < 50 else 0),
        "grades": grades,
        "bestScore": max(float(current.get("bestScore", 0)), float(percentage)),
        "optedIn": bool(current.get("optedIn", False)),
        "updatedAt": now(),
    })


def handler(event):
    try:
        if event.get("httpMethod", "GET") == "GET":
            return response({"entries": _public_entries(), "viewer": _viewer(event)})

        user = require_user(event)
        payload = body(event)
        if payload.get("action") != "join":
            return response({"error": "Unknown leaderboard action."}, 400)
        user_snapshot = db().collection("users").document(user["uid"]).get()
        user_data = user_snapshot.to_dict() if user_snapshot.exists else {}
        ref = db().collection(LEADERBOARD_COLLECTION).document(user["uid"])
        existing = ref.get()
        current = existing.to_dict() if existing.exists else {}
        ref.set({
            "displayName": _first_name(user_data.get("name"), _first_name(user.get("email", "Student"), "Student")),
            "profilePicture": user_data.get("profilePicture", ""),
            "perfectPercentage": int(current.get("perfectPercentage", current.get("perfectScores", 0))),
            "perfectScores": int(current.get("perfectPercentage", current.get("perfectScores", 0))),
            "examsTaken": int(current.get("examsTaken", current.get("examsPassed", 0))),
            "examsPassed": int(current.get("examsTaken", current.get("examsPassed", 0))),
            "passes": int(current.get("passes", 0)),
            "fails": int(current.get("fails", 0)),
            "grades": current.get("grades", {name: 0 for name in GRADE_NAMES}),
            "bestScore": float(current.get("bestScore", 0)),
            "optedIn": True,
            "updatedAt": now(),
        })
        return response({"ok": True})
    except Exception as exc:
        return json_error(exc)