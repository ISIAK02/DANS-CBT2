import os
import uuid
from datetime import timedelta

import cloudinary
import cloudinary.uploader
import cloudinary.utils

from _common import body, db, json_error, now, response, user_from_event


PROFILE_FOLDER = "cbt-profiles"
PICTURE_INTERVAL = timedelta(days=30)


def _cloudinary_setup():
    cloudinary.config(
        cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
        api_key=os.environ["CLOUDINARY_API_KEY"],
        api_secret=os.environ["CLOUDINARY_API_SECRET"],
        secure=True,
    )


def _record(uid):
    snapshot = db().collection("users").document(uid).get()
    return snapshot.to_dict() if snapshot.exists else {}


def _safe_profile(uid):
    data = _record(uid)
    return {
        "name": data.get("name", ""),
        "profilePicture": data.get("profilePicture", ""),
        "profilePictureChangedAt": data.get("profilePictureChangedAt"),
    }


def handler(event):
    try:
        user = user_from_event(event)
        payload = body(event)
        uid = user["uid"]
        action = payload.get("action")
        if action == "get":
            return response({"profile": _safe_profile(uid)})
        if action == "upload-signature":
            current = _record(uid)
            changed_at = current.get("profilePictureChangedAt")
            if changed_at:
                available_at = changed_at + PICTURE_INTERVAL
                if now() < available_at:
                    days = max(1, (available_at - now()).days + 1)
                    return response({"error": f"You can change your profile picture again in {days} day(s)."}, 429)
            _cloudinary_setup()
            timestamp = int(now().timestamp())
            public_id = uuid.uuid4().hex
            folder = f"{PROFILE_FOLDER}/{uid}"
            params = {"folder": folder, "public_id": public_id, "timestamp": timestamp}
            return response({
                "cloudName": os.environ["CLOUDINARY_CLOUD_NAME"],
                "apiKey": os.environ["CLOUDINARY_API_KEY"],
                "uploadUrl": f"https://api.cloudinary.com/v1_1/{os.environ['CLOUDINARY_CLOUD_NAME']}/image/upload",
                "publicId": public_id,
                "timestamp": timestamp,
                "signature": cloudinary.utils.api_sign_request(params, os.environ["CLOUDINARY_API_SECRET"]),
                "folder": folder,
            })
        if action == "update":
            name = str(payload.get("name", "")).strip()[:80]
            picture = str(payload.get("profilePicture", "")).strip()
            if not name or len(name) < 2:
                return response({"error": "Name or nickname must contain at least 2 characters."}, 422)
            updates = {"name": name, "updatedAt": now()}
            if picture:
                if not picture.startswith(f"https://res.cloudinary.com/"):
                    return response({"error": "Invalid profile picture."}, 422)
                current = _record(uid)
                old_picture = current.get("profilePicture", "")
                if picture != old_picture:
                    changed_at = current.get("profilePictureChangedAt")
                    if changed_at and now() < changed_at + PICTURE_INTERVAL:
                        available_at = changed_at + PICTURE_INTERVAL
                        days = max(1, (available_at - now()).days + 1)
                        return response({"error": f"You can change your profile picture again in {days} day(s)."}, 429)
                    updates.update({"profilePicture": picture, "profilePictureChangedAt": now()})
            db().collection("users").document(uid).set(updates, merge=True)
            leaderboard_ref = db().collection("leaderboard").document(uid)
            if leaderboard_ref.get().exists:
                leaderboard_ref.set({"displayName": name.split()[0][:40], "profilePicture": picture}, merge=True)
            return response({"profile": _safe_profile(uid)})
        return response({"error": "Unknown profile action."}, 400)
    except Exception as exc:
        return json_error(exc)
