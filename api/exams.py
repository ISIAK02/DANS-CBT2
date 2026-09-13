import random
import re
import uuid
from copy import deepcopy
from collections import Counter

from firebase_admin import firestore

from _common import active_subscription, body, db, json_error, now, require_user, response
from leaderboard import grade_for, update_after_exam


EXAM_DURATION = 3600
COACH_PROMPT_WORDS = {"according", "material", "which", "term", "completes", "statement", "concept", "illustrated", "passage", "identify", "identifies", "key", "word", "important", "idea", "expressed", "below", "best", "matches", "information", "given", "subject", "explained", "sentence", "choose", "answer", "correct", "connected", "mainly", "study"}


def _safe_attempt(attempt_id, data):
    return {"attemptId": attempt_id, "questions": [{"prompt": item["prompt"], "choices": item["choices"]} for item in data.get("questions", [])], "answers": data.get("answers", {}), "durationSeconds": EXAM_DURATION, "startedAt": data.get("startedAt")}


def _remaining_seconds(data):
    started = data.get("startedAt")
    if not started:
        return EXAM_DURATION
    return max(0, EXAM_DURATION - int((now() - started).total_seconds()))


def _submit_attempt(attempt_ref, data, answers):
    correct = sum(1 for index, question in enumerate(data["questions"]) if str(answers.get(str(index), "")) == str(question["answer"]))
    total = len(data["questions"])
    percentage = round(correct / total * 100, 1)
    result = {"status": "submitted", "answers": answers, "correct": correct, "incorrect": total - correct, "total": total, "percentage": percentage, "grade": grade_for(percentage), "submittedAt": now()}
    attempt_ref.update(result)
    return result


def _coach_snapshot(uid):
    attempts = [item.to_dict() for item in db().collection("examAttempts").where("userId", "==", uid).stream()]
    attempts = [item for item in attempts if item.get("status") == "submitted"]
    attempts.sort(key=lambda item: str(item.get("submittedAt", "")), reverse=True)
    banks = list(db().collection("questionBanks").where("userId", "==", uid).stream())
    bank_titles = {item.id: item.to_dict().get("title", "Study PDF") for item in banks}
    recent = attempts[:8]
    scores = [float(item.get("percentage", 0)) for item in recent]
    incorrect_terms = Counter()
    incorrect_count = 0
    for attempt in recent:
        answers = attempt.get("answers", {})
        for index, question in enumerate(attempt.get("questions", [])):
            selected = answers.get(str(index))
            if selected is None or str(selected) != str(question.get("answer", 0)):
                incorrect_count += 1
                words = re.findall(r"[A-Za-z]{5,}", question.get("prompt", "").lower())
                incorrect_terms.update(word for word in words if word not in COACH_PROMPT_WORDS)
    recommended = recent[0].get("bankId") if recent else (banks[0].id if banks else None)
    recommended_title = bank_titles.get(recommended, "")
    if not attempts:
        headline = "Your study coach is ready."
        detail = "Upload a study PDF, then complete your first practice exam so your plan can learn from your results."
        next_action = "Start with a fresh practice exam."
    else:
        average = round(sum(scores) / len(scores))
        if average < 60:
            headline = "Build the foundation first."
            detail = "Your recent results show that a focused review session will help more than another full-speed exam."
            next_action = "Review the missed questions, then retake a shorter focused set."
        elif average < 80:
            headline = "You are making progress."
            detail = "Your results are close enough for targeted practice to make the biggest difference."
            next_action = "Practice the areas you miss most before taking another full exam."
        else:
            headline = "You are in strong form."
            detail = "Your recent results are strong. Keep your accuracy high with a timed mixed practice session."
            next_action = "Take another timed exam and protect your weakest areas."
        scores.reverse()
    return {"hasData": bool(attempts), "headline": headline, "detail": detail, "nextAction": next_action, "average": round(sum(scores) / len(scores)) if scores else 0, "recentScores": scores, "questionsMissed": incorrect_count, "focusWords": [word.title() for word, _ in incorrect_terms.most_common(4)], "recommendedBankId": recommended, "recommendedBankTitle": recommended_title, "bankCount": len(banks)}


def handler(event):
    try:
        user = require_user(event)
        payload = body(event)
        if payload.get("action") == "history":
            records = db().collection("examAttempts").where("userId", "==", user["uid"]).stream()
            attempts = [{"id": item.id, **item.to_dict()} for item in records if item.to_dict().get("status") == "submitted"]
            attempts.sort(key=lambda item: str(item.get("submittedAt", "")), reverse=True)
            return response({"attempts": [{"id": item["id"], "bankId": item.get("bankId"), "correct": item.get("correct", 0), "incorrect": item.get("incorrect", 0), "total": item.get("total", len(item.get("questions", []))), "percentage": item.get("percentage", 0), "grade": item.get("grade", grade_for(item.get("percentage", 0))), "submittedAt": item.get("submittedAt")} for item in attempts[:20]]})
        if payload.get("action") == "coach":
            return response({"coach": _coach_snapshot(user["uid"])})
        if payload.get("action") == "current":
            records = db().collection("examAttempts").where("userId", "==", user["uid"]).where("status", "==", "in_progress").stream()
            active = next(iter(sorted(records, key=lambda item: str(item.to_dict().get("startedAt", "")), reverse=True)), None)
            if not active:
                return response({"attempt": None})
            data = active.to_dict()
            if _remaining_seconds(data) <= 0:
                _submit_attempt(active.reference, data, data.get("answers", {}))
                update_after_exam(user["uid"], round(sum(1 for index, question in enumerate(data["questions"]) if str(data.get("answers", {}).get(str(index), "")) == str(question["answer"])) / len(data["questions"]) * 100, 1))
                return response({"attempt": None})
            return response({"attempt": {**_safe_attempt(active.id, data), "remainingSeconds": _remaining_seconds(data)}})
        if payload.get("action") == "review":
            attempt_ref = db().collection("examAttempts").document(payload.get("attemptId", ""))
            attempt = attempt_ref.get()
            if not attempt.exists or attempt.to_dict().get("userId") != user["uid"]:
                return response({"error": "Exam attempt not found."}, 404)
            data = attempt.to_dict()
            if data.get("status") != "submitted":
                return response({"error": "This exam has not been submitted yet."}, 409)
            answers = data.get("answers", {})
            review = []
            for index, question in enumerate(data.get("questions", [])):
                correct_index = int(question.get("answer", 0))
                selected_index = answers.get(str(index))
                review.append({"number": index + 1, "prompt": question.get("prompt", ""), "selectedAnswer": question.get("choices", [])[int(selected_index)] if selected_index is not None and int(selected_index) < len(question.get("choices", [])) else "Not answered", "correctAnswer": question.get("choices", [])[correct_index], "correct": str(selected_index) == str(correct_index), "explanation": question.get("explanation", "")})
            return response({"attempt": {"id": attempt_ref.id, "correct": data.get("correct", 0), "incorrect": data.get("incorrect", 0), "total": data.get("total", len(review)), "percentage": data.get("percentage", 0), "grade": data.get("grade", grade_for(data.get("percentage", 0))), "submittedAt": data.get("submittedAt"), "review": review}})
        if payload.get("action") == "focused-start":
            if not active_subscription(user["uid"]):
                return response({"error": "An active subscription is required for CBT access."}, 403)
            source_ref = db().collection("examAttempts").document(payload.get("attemptId", ""))
            source = source_ref.get()
            if not source.exists or source.to_dict().get("userId") != user["uid"] or source.to_dict().get("status") != "submitted":
                return response({"error": "Submitted exam not found."}, 404)
            source_data = source.to_dict()
            answers = source_data.get("answers", {})
            missed = [deepcopy(question) for index, question in enumerate(source_data.get("questions", [])) if str(answers.get(str(index), "")) != str(question.get("answer", 0))]
            if not missed:
                return response({"error": "There are no missed questions in this exam."}, 422)
            random.shuffle(missed)
            selected = missed[:50]
            attempt_id = uuid.uuid4().hex
            started_at = now()
            db().collection("examAttempts").document(attempt_id).set({"userId": user["uid"], "bankId": source_data.get("bankId"), "sourceAttemptId": source_ref.id, "mode": "focused", "questions": selected, "answers": {}, "status": "in_progress", "startedAt": started_at, "createdAt": started_at})
            return response({**_safe_attempt(attempt_id, {"questions": selected, "answers": {}, "startedAt": started_at}), "remainingSeconds": EXAM_DURATION, "focused": True})
        if payload.get("action") == "bookmark":
            question = payload.get("question") or {}
            if payload.get("attemptId") is not None:
                source = db().collection("examAttempts").document(payload.get("attemptId", "")).get()
                if not source.exists or source.to_dict().get("userId") != user["uid"]:
                    return response({"error": "Exam attempt not found."}, 404)
                source_questions = source.to_dict().get("questions", [])
                question_number = int(payload.get("questionNumber", 0)) - 1
                question = source_questions[question_number] if 0 <= question_number < len(source_questions) else {}
            if not question.get("prompt") or not isinstance(question.get("choices"), list):
                return response({"error": "Invalid question bookmark."}, 422)
            bookmark_id = payload.get("bookmarkId") or uuid.uuid4().hex
            db().collection("users").document(user["uid"]).collection("bookmarks").document(bookmark_id).set({"prompt": str(question["prompt"])[:1000], "choices": question["choices"][:4], "answer": int(question.get("answer", 0)), "explanation": str(question.get("explanation", ""))[:1500], "createdAt": now()}, merge=True)
            return response({"bookmarkId": bookmark_id})
        if payload.get("action") == "bookmarks":
            records = db().collection("users").document(user["uid"]).collection("bookmarks").stream()
            bookmarks = [{"id": item.id, **item.to_dict()} for item in records]
            bookmarks.sort(key=lambda item: str(item.get("createdAt", "")), reverse=True)
            return response({"bookmarks": bookmarks[:100]})
        if payload.get("action") == "start":
            if not active_subscription(user["uid"]):
                return response({"error": "An active subscription is required for CBT access."}, 403)
            existing = db().collection("examAttempts").where("userId", "==", user["uid"]).where("status", "==", "in_progress").stream()
            existing = next(iter(sorted(existing, key=lambda item: str(item.to_dict().get("startedAt", "")), reverse=True)), None)
            if existing:
                existing_data = existing.to_dict()
                if _remaining_seconds(existing_data) > 0:
                    return response({**_safe_attempt(existing.id, existing_data), "remainingSeconds": _remaining_seconds(existing_data), "resumed": True})
                expired_result = _submit_attempt(existing.reference, existing_data, existing_data.get("answers", {}))
                update_after_exam(user["uid"], expired_result["percentage"])
            bank_ref = db().collection("questionBanks").document(payload.get("bankId", ""))
            bank = bank_ref.get()
            if not bank.exists or bank.to_dict().get("userId") != user["uid"]:
                return response({"error": "Question bank not found."}, 404)
            questions = bank.to_dict().get("questions", [])
            if len(questions) < 50:
                return response({"error": "This question bank does not have enough questions."}, 422)
            selected = random.sample(questions, 50)
            for question in selected:
                correct_text = question["choices"][question.get("answer", 0)]
                random.shuffle(question["choices"])
                question["answer"] = question["choices"].index(correct_text)
            attempt_id = uuid.uuid4().hex
            started_at = now()
            db().collection("examAttempts").document(attempt_id).set({"userId": user["uid"], "bankId": bank_ref.id, "questions": selected, "answers": {}, "status": "in_progress", "startedAt": started_at, "createdAt": started_at})
            return response({**_safe_attempt(attempt_id, {"questions": selected, "answers": {}, "startedAt": started_at}), "remainingSeconds": EXAM_DURATION})
        if payload.get("action") == "save":
            attempt_ref = db().collection("examAttempts").document(payload.get("attemptId", ""))
            attempt = attempt_ref.get()
            if not attempt.exists or attempt.to_dict().get("userId") != user["uid"]:
                return response({"error": "Exam attempt not found."}, 404)
            data = attempt.to_dict()
            if data.get("status") != "in_progress":
                return response({"error": "This exam has already been submitted."}, 409)
            if _remaining_seconds(data) <= 0:
                result = _submit_attempt(attempt_ref, data, data.get("answers", {}))
                update_after_exam(user["uid"], result["percentage"])
                return response({"expired": True, **result})
            answers = payload.get("answers", {})
            if not isinstance(answers, dict):
                return response({"error": "Invalid exam answers."}, 422)
            attempt_ref.update({"answers": answers, "updatedAt": now()})
            return response({"saved": True, "remainingSeconds": _remaining_seconds(data)})
        if payload.get("action") == "submit":
            attempt_ref = db().collection("examAttempts").document(payload.get("attemptId", ""))
            attempt = attempt_ref.get()
            if not attempt.exists or attempt.to_dict().get("userId") != user["uid"]:
                return response({"error": "Exam attempt not found."}, 404)
            data = attempt.to_dict()
            if data.get("status") != "in_progress":
                return response({"error": "This exam has already been submitted."}, 409)
            answers = payload.get("answers", {})
            result = _submit_attempt(attempt_ref, data, answers)
            update_after_exam(user["uid"], result["percentage"])
            return response(result)
        return response({"error": "Unknown exam action."}, 400)
    except Exception as exc:
        return json_error(exc)