import os
import uuid

import cloudinary
import cloudinary.uploader
import cloudinary.utils

from _common import body, db, json_error, now, require_admin, response


VIDEO_FOLDER = "cbt-instruction"
VIDEO_DOCUMENT = "instructionVideo"
VERIFY_VIDEO_DOCUMENT = "verifyEmailVideo"


def _cloudinary_setup():
    cloudinary.config(
        cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
        api_key=os.environ["CLOUDINARY_API_KEY"],
        api_secret=os.environ["CLOUDINARY_API_SECRET"],
        secure=True,
    )


def _video_record(document=VIDEO_DOCUMENT):
    snapshot = db().collection("siteContent").document(document).get()
    return snapshot.to_dict() if snapshot.exists else None


def handler(event):
    try:
        method = event.get("httpMethod", "GET")
        if method == "GET":
            return response({"video": _video_record(), "verifyVideo": _video_record(VERIFY_VIDEO_DOCUMENT)})

        admin = require_admin(event)
        payload = body(event)
        action = payload.get("action")
        document = VERIFY_VIDEO_DOCUMENT if payload.get("videoType") == "verify-email" else VIDEO_DOCUMENT

        if action == "upload-signature":
            _cloudinary_setup()
            timestamp = int(now().timestamp())
            public_id = uuid.uuid4().hex
            params = {
                "folder": VIDEO_FOLDER,
                "public_id": public_id,
                "timestamp": timestamp,
            }
            return response({
                "cloudName": os.environ["CLOUDINARY_CLOUD_NAME"],
                "apiKey": os.environ["CLOUDINARY_API_KEY"],
                "uploadUrl": f"https://api.cloudinary.com/v1_1/{os.environ['CLOUDINARY_CLOUD_NAME']}/video/upload",
                "publicId": public_id,
                "timestamp": timestamp,
                "signature": cloudinary.utils.api_sign_request(params, os.environ["CLOUDINARY_API_SECRET"]),
                "folder": VIDEO_FOLDER,
            })

        if action == "publish":
            public_id = str(payload.get("publicId", ""))
            if not public_id.startswith(f"{VIDEO_FOLDER}/"):
                return response({"error": "Invalid instructional video upload."}, 422)
            title = str(payload.get("title", "How to verify your email" if document == VERIFY_VIDEO_DOCUMENT else "How to use DANS CBT")).strip()[:120]
            if not title:
                return response({"error": "A video title is required."}, 422)
            _cloudinary_setup()
            video_url, _ = cloudinary.utils.cloudinary_url(public_id, resource_type="video", secure=True)
            record = {
                "title": title,
                "videoUrl": video_url,
                "publicId": public_id,
                "updatedAt": now(),
                "updatedBy": admin["uid"],
            }
            db().collection("siteContent").document(document).set(record)
            return response({"video": record})

        if action == "delete":
            record = _video_record(document)
            if record and record.get("publicId", "").startswith(f"{VIDEO_FOLDER}/"):
                _cloudinary_setup()
                cloudinary.uploader.destroy(record["publicId"], resource_type="video", invalidate=True)
            db().collection("siteContent").document(document).delete()
            return response({"ok": True})

        return response({"error": "Unknown video action."}, 400)
    except Exception as exc:
        return json_error(exc)
