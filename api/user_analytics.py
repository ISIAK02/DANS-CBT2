from _common import db, json_error, require_user, response


def handler(event):
    try:
        user = require_user(event)
        attempts = [item.to_dict() for item in db().collection("examAttempts").where("userId", "==", user["uid"]).stream()]
        submitted = [item for item in attempts if item.get("status") == "submitted"]
        scores = [float(item.get("percentage", 0)) for item in submitted]
        passed = sum(1 for score in scores if score >= 50)
        return response({"analytics": {
            "examsTaken": len(submitted),
            "passed": passed,
            "failed": len(submitted) - passed,
            "averageScore": round(sum(scores) / len(scores), 1) if scores else 0,
        }})
    except Exception as exc:
        return json_error(exc)
