"""TinyFish site discovery, privacy-policy retrieval, and initial HTML signals."""

import json
import os
import re
import sys
from html.parser import HTMLParser
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

TINYFISH_API_KEY = os.getenv("TINYFISH_API_KEY")
TINYFISH_RUN_URL = "https://agent.tinyfish.ai/v1/automation/run"

GOAL_TEMPLATE = """
Visit the supplied site as an ordinary logged-out visitor. Do not sign up, log in, submit forms, or change settings.

Find the site's privacy policy (check the footer and links called Privacy, Privacy Policy, Privacy Notice, or Data Policy). Open it and read the policy. Return the full policy text so the user can expand it in the report, plus a policy-grounded analysis.

Observe only what is visibly available on the initial site page: site name, whether a cookie banner or settings link is visible, and whether sign-up/login is offered. Do not claim that a banner was accepted or that post-consent tracking was tested.

Return JSON only, matching this structure:
{
  "site_name": "string",
  "policy_url": "full URL or null",
  "policy_text": "full text or null",
  "has_cookie_banner": true,
  "has_signup_or_login": false,
  "policy_analysis": {
    "headline": "one short finding",
    "summary": "2-3 plain-language sentences about data, sharing, purposes, and choices",
    "score": 0,
    "grade": "F",
    "score_basis": "why the policy receives this transparency score; do not claim this proves real-world behavior",
    "pillars": {
      "information_collected": "specific policy statement",
      "purpose_of_collection": "specific policy statement",
      "third_party_sharing": "specific policy statement",
      "advertising_and_profiling": "specific policy statement",
      "data_retention": "specific policy statement",
      "international_transfers": "specific policy statement",
      "security_practices": "specific policy statement",
      "user_rights_and_deletion": "specific policy statement"
    },
    "facts": {
      "data_collected": ["specific categories"],
      "third_parties": ["recipient types"],
      "can_delete_account": true,
      "retention_period": "stated period or null"
    },
    "sharing_details": [
      {
        "data_categories": ["specific data categories linked by the policy"],
        "recipient": "named recipient or recipient type",
        "purpose": "stated purpose",
        "requirement": "required_for_service | optional | legally_required | context_dependent | not_stated",
        "reason": "brief explanation grounded in the policy",
        "evidence": "short exact policy excerpt, at most 20 words"
      }
    ],
    "privacy_controls": [
      {"control": "name", "how_to_use": "policy-stated steps", "evidence": "short exact excerpt"}
    ],
    "deletion_steps": [
      {"step": "step title", "detail": "policy-stated action; never say it was completed", "evidence": "short exact excerpt"}
    ],
    "reasons": ["short policy-based scoring reason"]
  }
}

Use this grading rubric: A 90-100, B 80-89, C 70-79, D 60-69, F 0-59. Score clarity, specificity, limits, and user choices in the policy. Classify each sharing flow separately. Use required_for_service only when the policy ties it to delivering the service; optional only for an explicit choice/control; legally_required only for legal obligations; context_dependent when the policy states conditions; otherwise not_stated. Do not infer links between data and recipients when the policy does not make them. Use null, empty arrays, or not_stated for missing information. Keep all evidence quotes short and exact.
"""

KNOWN_TRACKERS = {
    "google-analytics.com": "Google Analytics",
    "googletagmanager.com": "Google Tag Manager",
    "doubleclick.net": "Google Ads / DoubleClick",
    "googlesyndication.com": "Google Ads",
    "connect.facebook.net": "Meta Pixel",
    "facebook.net": "Meta",
    "analytics.twitter.com": "X Analytics",
    "ads-twitter.com": "X Ads",
    "snap.licdn.com": "LinkedIn Insight Tag",
    "analytics.tiktok.com": "TikTok Pixel",
    "static.hotjar.com": "Hotjar Session Replay",
    "script.hotjar.com": "Hotjar Session Replay",
    "cdn.segment.com": "Segment",
    "api.mixpanel.com": "Mixpanel",
    "cdn.mxpnl.com": "Mixpanel",
    "js.hs-scripts.com": "HubSpot",
    "bat.bing.com": "Microsoft Advertising",
    "clarity.ms": "Microsoft Clarity",
    "criteo.com": "Criteo",
    "taboola.com": "Taboola",
    "outbrain.com": "Outbrain",
    "amplitude.com": "Amplitude",
    "fullstory.com": "FullStory Session Replay",
}

TRACKER_CATEGORIES = {
    "Google Analytics": "Analytics",
    "Google Tag Manager": "Tag manager",
    "Google Ads / DoubleClick": "Advertising",
    "Google Ads": "Advertising",
    "Meta Pixel": "Advertising",
    "Meta": "Advertising",
    "X Analytics": "Analytics",
    "X Ads": "Advertising",
    "LinkedIn Insight Tag": "Advertising",
    "TikTok Pixel": "Advertising",
    "Hotjar Session Replay": "Session replay",
    "Segment": "Analytics platform",
    "Mixpanel": "Analytics",
    "HubSpot": "Marketing / analytics",
    "Microsoft Advertising": "Advertising",
    "Microsoft Clarity": "Session replay",
    "Criteo": "Advertising",
    "Taboola": "Advertising",
    "Outbrain": "Advertising",
    "Amplitude": "Analytics",
    "FullStory Session Replay": "Session replay",
}


def normalize_url(url: str) -> str:
    """Add https:// when a hostname is entered without a scheme."""
    url = url.strip()
    if not re.match(r"^https?://", url, flags=re.I):
        url = "https://" + url
    return url


def call_tinyfish(url: str, goal: str, timeout: int = 300) -> dict:
    """Send a browser-agent goal to TinyFish and return its JSON response."""
    if not TINYFISH_API_KEY:
        raise RuntimeError("TINYFISH_API_KEY is missing. Add it to the project's .env file.")

    response = requests.post(
        TINYFISH_RUN_URL,
        headers={"X-API-Key": TINYFISH_API_KEY, "Content-Type": "application/json"},
        json={"url": url, "goal": goal},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def parse_result(raw: dict) -> dict:
    """TinyFish may return its result as a dict or a JSON string."""
    result = raw.get("result", raw)
    if isinstance(result, str):
        cleaned = re.sub(r"^```(?:json)?|```$", "", result.strip(), flags=re.M).strip()
        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError:
            result = {"policy_text": cleaned}
    if not isinstance(result, dict):
        return {}
    analysis = result.get("policy_analysis")
    if isinstance(analysis, str):
        try:
            result["policy_analysis"] = json.loads(analysis)
        except json.JSONDecodeError:
            result["policy_analysis"] = None
    return result


class _ResourceParser(HTMLParser):
    """Collect resource URLs referenced by initial HTML tags."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.resources = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "iframe", "img", "source") and attrs.get("src"):
            self.resources.append((tag, attrs["src"]))
        elif tag == "link" and attrs.get("href"):
            rel = set((attrs.get("rel") or "").lower().split())
            if rel.intersection({"stylesheet", "preload", "preconnect"}):
                self.resources.append(("link", attrs["href"]))


def _tracker_for(host: str):
    for tracker_domain, name in KNOWN_TRACKERS.items():
        if host == tracker_domain or host.endswith("." + tracker_domain):
            return name
    return None


def check_trackers(url: str) -> dict:
    """Inspect initial HTML resource references; this does not execute page scripts."""
    page_request = {"method": "GET", "url": url, "status": None, "final_url": url}
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (DataTrail privacy scanner)"},
            timeout=20,
        )
        page_request.update({"status": response.status_code, "final_url": response.url})
        response.raise_for_status()
        html = response.text
    except requests.RequestException as exc:
        page_request["error"] = type(exc).__name__
        return {"page_request": page_request, "tracker_findings": []}

    parser = _ResourceParser()
    parser.feed(html)
    own_host = (urlparse(page_request["final_url"]).hostname or "").lower()
    collected = {}
    for source_type, source_url in parser.resources:
        parsed = urlparse(source_url if "//" in source_url else "//" + source_url)
        host = (parsed.hostname or "").lower()
        if not host or host == own_host:
            continue
        tracker = _tracker_for(host)
        if not tracker:
            continue
        key = (tracker, host, source_type)
        if key not in collected:
            collected[key] = {
                "tracker": tracker,
                "domain": host,
                "category": TRACKER_CATEGORIES.get(tracker, "Unclassified"),
                "reference_type": source_type,
                "evidence": "Initial HTML resource reference",
                "occurrences": 0,
            }
        collected[key]["occurrences"] += 1

    return {"page_request": page_request, "tracker_findings": list(collected.values())}


def scan_site(url: str) -> dict:
    """Find and read a privacy policy, extract policy-grounded insights, and inspect initial HTML."""
    url = normalize_url(url)
    output = {
        "url": url,
        "site_name": None,
        "policy_url": None,
        "policy_text": None,
        "has_cookie_banner": None,
        "has_signup_or_login": None,
        "policy_analysis": None,
        "page_request": {"method": "GET", "url": url, "status": None, "final_url": url},
        "tracker_findings": [],
        "error": None,
    }

    try:
        data = parse_result(call_tinyfish(url, GOAL_TEMPLATE))
        for key in ("site_name", "policy_url", "policy_text", "has_cookie_banner", "has_signup_or_login", "policy_analysis"):
            output[key] = data.get(key)
        if not output["policy_text"]:
            output["error"] = "TinyFish could not find or read a privacy policy."
    except Exception as exc:
        output["error"] = f"{type(exc).__name__}: {exc}"

    signals = check_trackers(url)
    output["page_request"] = signals["page_request"]
    output["tracker_findings"] = signals["tracker_findings"]
    return output


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "https://www.spotify.com"
    report = scan_site(target)
    preview = dict(report)
    if preview["policy_text"]:
        preview["policy_text"] = preview["policy_text"][:300] + "... [trimmed]"
    print(json.dumps(preview, indent=2, ensure_ascii=False))
