import json
import os
import re
import requests
from dotenv import load_dotenv

load_dotenv()

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
MAX_POLICY_CHARS = 30000

SYSTEM_PROMPT = """You are a careful privacy policy analyst. Use only the supplied privacy policy text for policy claims. The supplied page-scan signals are separate technical evidence and do not prove data was transmitted.

Return one valid JSON object with this shape:
{
  "headline": "One short plain-language finding.",
  "summary": "Two or three sentences: data collected, who it is shared with, purposes, and user choices.",
  "score": 0,
  "grade": "F",
  "score_basis": "Explain the policy-transparency score, not the site's actual security or behavior.",
  "pillars": {
    "information_collected": "Specific categories stated in the policy.",
    "purpose_of_collection": "Purposes stated in the policy.",
    "third_party_sharing": "Recipient types and the data/purpose links the policy makes.",
    "advertising_and_profiling": "Advertising, profiling, and controls.",
    "data_retention": "Retention periods or criteria.",
    "international_transfers": "Cross-border transfers and safeguards.",
    "security_practices": "Security measures the policy states.",
    "user_rights_and_deletion": "Rights and deletion instructions stated in the policy."
  },
  "facts": {
    "data_collected": ["specific categories"],
    "third_parties": ["recipient types"],
    "can_delete_account": true,
    "retention_period": "stated period or null"
  },
  "sharing_details": [
    {
      "data_categories": ["specific categories"],
      "recipient": "named recipient or recipient type",
      "purpose": "stated purpose",
      "requirement": "required_for_service | optional | legally_required | context_dependent | not_stated",
      "reason": "Why that requirement label follows from the policy.",
      "evidence": "Short exact excerpt, at most 20 words."
    }
  ],
  "privacy_controls": [
    {"control": "control name", "how_to_use": "policy-stated steps", "evidence": "short excerpt"}
  ],
  "deletion_steps": [
    {"step": "step title", "detail": "policy-stated action", "evidence": "short excerpt"}
  ],
  "reasons": ["Short policy-based reason affecting the score."]
}

Scoring: A=90-100, B=80-89, C=70-79, D=60-69, F=0-59. Score policy clarity, specificity, limits, and user choices. Do not treat policy wording as proof that behavior matches it. Use null, empty arrays, or "not_stated" when the policy does not say. Do not infer that sharing is necessary merely because it occurs. Classify each sharing flow separately: required_for_service only when the policy ties it to providing the service; optional when the policy gives a genuine choice or opt-out; legally_required only for legal obligations; context_dependent when the policy states conditions; otherwise not_stated. When policy tables do not explicitly link a data category to a recipient, say so in reason and avoid inventing the link. Keep evidence excerpts brief and exact."""


def grade_for_score(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def normalize_analysis(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Policy analysis is not a JSON object.")
    normalized = dict(value)
    try:
        score = int(float(value.get("score")))
    except (TypeError, ValueError):
        score = None
    if score is not None:
        score = max(0, min(100, score))
    normalized["score"] = score
    normalized["grade"] = grade_for_score(score) if score is not None else None
    normalized["pillars"] = value.get("pillars") if isinstance(value.get("pillars"), dict) else {}
    normalized["facts"] = value.get("facts") if isinstance(value.get("facts"), dict) else {}
    normalized["sharing_details"] = [item for item in value.get("sharing_details", []) if isinstance(item, dict)] if isinstance(value.get("sharing_details"), list) else []
    normalized["privacy_controls"] = [item for item in value.get("privacy_controls", []) if isinstance(item, dict)] if isinstance(value.get("privacy_controls"), list) else []
    normalized["deletion_steps"] = [item for item in value.get("deletion_steps", []) if isinstance(item, dict)] if isinstance(value.get("deletion_steps"), list) else []
    normalized["reasons"] = value.get("reasons") if isinstance(value.get("reasons"), list) else []
    return normalized


def analyze(policy_text: str, tracker_findings: list = None) -> dict:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing.")

    evidence = {
        "privacy_policy_text": policy_text[:MAX_POLICY_CHARS],
        "initial_html_tracker_references": tracker_findings or [],
    }
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": json.dumps(evidence, ensure_ascii=False)}]}],
        "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 6000},
    }

    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json=body,
        timeout=60,
    )
    if not response.ok:
        raise RuntimeError(f"Gemini error {response.status_code}: {response.text[:300]}")

    text = response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    return normalize_analysis(json.loads(text))
