import re
from collections import Counter

import fitz


STOP = set("a an and are as at be by for from has have in is it its of on or that the their this to was were with".split())


def _clean(text):
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"[^\w\s,.;:()/%'-]", "", text)


def _sentences(text):
    return [item.strip() for item in re.split(r"(?<=[.!?])\s+", text) if 45 <= len(item.strip()) <= 360]


def _terms(sentence):
    terms = re.findall(r"\b[A-Za-z][A-Za-z-]{4,}\b", sentence)
    return list(dict.fromkeys(item for item in terms if item.lower() not in STOP))


def _choices(answer, pool, used_options, offset):
    candidates = []
    seen = {answer.lower()}
    for item in pool:
        candidate = item.strip().rstrip(".")
        key = candidate.lower()
        if key not in seen and 2 < len(candidate) < 40:
            candidates.append(candidate)
            seen.add(key)
    candidates.sort(key=lambda item: (used_options[item.lower()], (sum(ord(char) for char in item.lower()) + offset) % 17))
    alternatives = candidates[:3]
    if len(alternatives) < 3:
        return []
    choices = [answer] + alternatives
    return choices


def _question_stem(sentence, answer, mode):
    if mode == 0:
        prompt = re.sub(r"\b" + re.escape(answer) + r"\b", "_____", sentence, count=1, flags=re.I)
        return f"Which term completes the statement from the study material? {prompt}"
    if mode == 1:
        return f"Which concept is illustrated by this statement? {sentence}"
    if mode == 2:
        return f"What does this passage identify as a key term? {sentence}"
    if mode == 3:
        return f"Which term best matches the idea expressed below? {sentence}"
    if mode == 4:
        return f"Based on the study material, which answer is most closely connected to this statement? {sentence}"
    if mode == 5:
        return f"Which subject is being explained in this sentence? {sentence}"
    if mode == 6:
        return f"Choose the term that best represents the information given: {sentence}"
    prompt = re.sub(r"\b" + re.escape(answer) + r"\b", "_____", sentence, count=1, flags=re.I)
    return f"Complete this study statement with the correct term: {prompt}"


def build_question_bank(stream):
    document = fitz.open(stream=stream.read(), filetype="pdf")
    text = _clean(" ".join(page.get_text("text") for page in document))
    sentences = _sentences(text)
    if len(sentences) < 50:
        return {"pageCount": len(document), "questions": []}
    terms = [word for word in re.findall(r"[A-Za-z][A-Za-z-]{4,}", text) if word.lower() not in STOP]
    frequencies = Counter(word.lower() for word in terms)
    distractor_pool = list(dict.fromkeys(terms))
    questions = []
    seen = set()
    seen_options = set()
    used_options = Counter()
    for question_number, sentence in enumerate(sentences):
        candidates = _terms(sentence)
        if not candidates:
            continue
        ranked = sorted(candidates, key=lambda item: (len(item), frequencies[item.lower()]), reverse=True)
        answer = ranked[question_number % min(3, len(ranked))]
        mode = question_number % 8
        correct_index = 0
        if mode == 7:
            false_term = next((item for item in distractor_pool if item.lower() not in sentence.lower() and item.lower() != answer.lower()), None)
            is_true = question_number % 10 == 3
            statement = sentence if is_true or not false_term else re.sub(r"\b" + re.escape(answer) + r"\b", false_term, sentence, count=1, flags=re.I)
            correct_index = 0 if is_true or not false_term else 1
            stem = f"True or false: {statement}"
        else:
            stem = _question_stem(sentence, answer, mode)
        key = stem.lower()
        if key in seen:
            continue
        choices = ["True", "False"] if mode == 7 else _choices(answer, distractor_pool, used_options, question_number)
        option_key = tuple(sorted(choice.lower() for choice in choices))
        if not choices or (mode != 7 and option_key in seen_options):
            continue
        seen.add(key)
        seen_options.add(option_key)
        for choice in choices:
            used_options[choice.lower()] += 1
        questions.append({"prompt": stem, "choices": choices, "answer": correct_index, "explanation": sentence})
        if len(questions) >= 150:
            break
    return {"pageCount": len(document), "questions": questions}