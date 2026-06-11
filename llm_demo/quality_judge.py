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
    if delta > 0.05:
        return "with_scored_higher"
    if delta < -0.05:
        return "with_scored_lower"
    return "similar"
