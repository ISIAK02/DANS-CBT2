import base64
import io
import os
import urllib.request
import uuid

import cloudinary
import cloudinary.utils
from firebase_admin import firestore

from _common import body, db, json_error, now, require_user, response, active_subscription
from pdf_engine import build_question_bank


def _cloudinary_setup():
    cloudinary.config(
        cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
        api_key=os.environ["CLOUDINARY_API_KEY"],
        api_secret=os.environ["CLOUDINARY_API_SECRET"],
        secure=True,
    )


def _pdf_folder(uid):
    return f"cbt-pdfs/{uid}"


def _download_cloudinary_pdf(public_id, version):
    if not public_id.startswith("cbt-pdfs/"):
        raise PermissionError("PDF upload does not belong to this account.")
    _cloudinary_setup()
    url, _ = cloudinary.utils.cloudinary_url(
        public_id,
        resource_type="raw",
        type="authenticated",
        version=version,
        sign_url=True,
        secure=True,
    )
    with urllib.request.urlopen(url, timeout=30) as download:
        return download.read()


def handler(event):
    try:
        user = require_user(event)
        if not active_subscription(user["uid"]):
            return response({"error": "An active subscription is required for CBT access."}, 403)
        payload = body(event)
        if payload.get("action") == "list":
            records = db().collection("questionBanks").where("userId", "==", user["uid"]).stream()
            banks = [{"id": item.id, **item.to_dict()} for item in records]
            banks.sort(key=lambda item: str(item.get("createdAt", "")), reverse=True)
            return response({"banks": banks[:20]})
        if payload.get("action") == "upload-signature":
            _cloudinary_setup()
            timestamp = int(now().timestamp())
            public_id = uuid.uuid4().hex
            params = {
                "folder": _pdf_folder(user["uid"]),
                "public_id": public_id,
                "timestamp": timestamp,
                "type": "authenticated",
            }
            return response({
                "cloudName": os.environ["CLOUDINARY_CLOUD_NAME"],
                "apiKey": os.environ["CLOUDINARY_API_KEY"],
                "uploadUrl": f"https://api.cloudinary.com/v1_1/{os.environ['CLOUDINARY_CLOUD_NAME']}/raw/upload",
                "publicId": public_id,
                "timestamp": timestamp,
                "signature": cloudinary.utils.api_sign_request(params, os.environ["CLOUDINARY_API_SECRET"]),
                "folder": params["folder"],
                "type": params["type"],
            })
        if payload.get("action") != "process":
            return response({"error": "Unknown document action."}, 400)
        if payload.get("cloudinaryPublicId"):
            public_id = payload["cloudinaryPublicId"]
            if not public_id.startswith(f"{_pdf_folder(user['uid'])}/"):
                return response({"error": "PDF upload does not belong to this account."}, 403)
            content = _download_cloudinary_pdf(public_id, payload.get("cloudinaryVersion"))
        else:
            raw = payload.get("fileData", "")
            if not raw.startswith("data:application/pdf;base64,"):
                return response({"error": "Upload a real PDF document."}, 422)
            content = base64.b64decode(raw.split(",", 1)[1])
        if content[:4] != b"%PDF":
            return response({"error": "The file signature is not a valid PDF."}, 422)
        result = build_question_bank(io.BytesIO(content))
        if len(result["questions"]) < 50:
            return response({"error": "There is not enough reliable readable content to create 50 questions."}, 422)
        document_id = uuid.uuid4().hex
        bank_id = uuid.uuid4().hex
        db().collection("documents").document(document_id).set({"userId": user["uid"], "name": payload.get("fileName", "Study PDF"), "pageCount": result["pageCount"], "cloudinaryPublicId": payload.get("cloudinaryPublicId", ""), "createdAt": now(), "status": "ready"})
        db().collection("questionBanks").document(bank_id).set({"userId": user["uid"], "documentId": document_id, "title": payload.get("fileName", "Study PDF"), "questions": result["questions"], "questionCount": len(result["questions"]), "createdAt": now()})
        return response({"bankId": bank_id, "questionCount": len(result["questions"]), "title": payload.get("fileName", "Study PDF")}, 201)
    except Exception as exc:
        return json_error(exc)