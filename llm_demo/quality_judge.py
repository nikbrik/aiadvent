import json
import re


def build_judge_messages(question, answer, ground_truth):
    payload = {
        "question": question,
        "model_answer": answer,
        "ground_truth": ground_truth,
        "instructions": (
            "Compare model_answer against ground_truth for the question. "
            "Return only valid JSON with keys passed (bool), score (0.0-1.0), note (short string). "
            "Score 1.0 only if all ground_truth facts are present and correct."
        ),
    }
    return [
        {
            "role": "system",
            "content": "You evaluate answer quality for a compression demo. Return JSON only.",
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def judge_answer(llm, question, answer, ground_truth, llm_options):
    messages = build_judge_messages(question, answer, ground_truth)
    completion = llm(messages=messages, **llm_options)
    return parse_judge_result(completion.get("content") or "")


def evaluate_fact_recall(answer, ground_truth):
    answer_text = str(answer or "")
    answer_upper = answer_text.upper()
    facts = []
    for key, value in (ground_truth or {}).items():
        token = str(value or "").strip()
        found = bool(token) and token.upper() in answer_upper
        facts.append({
            "key": str(key),
            "value": token,
            "found": found,
        })

    total = len(facts) or 1
    found_count = sum(1 for item in facts if item["found"])
    score = found_count / total
    passed = found_count == total
    missing = [item["value"] for item in facts if not item["found"]]
    if passed:
        note = "All required facts present."
    elif missing:
        note = f"Missing: {', '.join(missing)}."
    else:
        note = "Required facts not found."

    return {
        "passed": passed,
        "score": score,
        "note": note,
        "facts": facts,
        "source": "deterministic",
    }


def merge_judge_results(fact_check, llm_judge):
    fact_check = fact_check or {}
    llm_judge = llm_judge or {}
    fact_score = float(fact_check.get("score") or 0.0)
    llm_score = float(llm_judge.get("score") or 0.0)
    if fact_check.get("passed"):
        score = 1.0
        passed = True
    else:
        score = min(fact_score, llm_score) if llm_judge else fact_score
        passed = False
    notes = []
    if fact_check.get("note"):
        notes.append(str(fact_check["note"]))
    if llm_judge.get("note"):
        notes.append(str(llm_judge["note"]))
    return {
        "passed": passed,
        "score": max(0.0, min(1.0, score)),
        "note": " · ".join(notes) if notes else "",
        "facts": fact_check.get("facts") or [],
        "llm_score": llm_score if llm_judge else None,
    }


def judge_recall_answer(llm, question, answer, ground_truth, llm_options):
    fact_check = evaluate_fact_recall(answer, ground_truth)
    try:
        llm_judge = judge_answer(llm, question, answer, ground_truth, llm_options)
    except Exception as exc:
        llm_judge = {
            "passed": False,
            "score": 0.0,
            "note": f"judge failed: {exc}",
        }
    return merge_judge_results(fact_check, llm_judge)


def safe_judge_recall_answer(llm, question, answer, ground_truth, llm_options):
    try:
        return judge_recall_answer(llm, question, answer, ground_truth, llm_options)
    except Exception as exc:
        fact_check = evaluate_fact_recall(answer, ground_truth)
        fact_check["note"] = f"judge failed: {exc}"
        fact_check["passed"] = False
        fact_check["score"] = 0.0
        return fact_check


def safe_judge_answer(llm, question, answer, ground_truth, llm_options):
    try:
        return judge_answer(llm, question, answer, ground_truth, llm_options)
    except Exception as exc:
        return {
            "passed": False,
            "score": 0.0,
            "note": f"judge failed: {exc}",
        }


def parse_judge_result(text):
    data = parse_json_object(text)
    passed = bool(data.get("passed"))
    score_raw = data.get("score", 0)
    try:
        score = float(score_raw)
    except (TypeError, ValueError):
        score = 0.0
    score = max(0.0, min(1.0, score))
    note = str(data.get("note") or "").strip()
    return {
        "passed": passed,
        "score": score,
        "note": note,
    }


def parse_json_object(text):
    text = str(text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise ValueError("judge JSON must be an object")
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("judge JSON must be an object")
    return data


def quality_delta(without_score, with_score):
    delta = with_score - without_score
    if abs(delta) <= 0.05:
        if without_score >= 0.99 and with_score >= 0.99:
            return "equivalent_recall"
        return "similar"
    if delta > 0.05:
        return "with_scored_higher"
    return "with_scored_lower"
