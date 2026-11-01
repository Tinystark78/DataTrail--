import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import analyzer
import store
import tinyfish_agent

load_dotenv()

app = FastAPI(title="DataTrail Privacy Report")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScanRequest(BaseModel):
    url: str


def _page() -> str:
    html_path = Path(__file__).parent / "index.html"
    if not html_path.exists():
        return "<h1>Error: index.html not found in the same folder as main.py</h1>"
    return html_path.read_text(encoding="utf-8")


@app.get("/", include_in_schema=False, response_class=HTMLResponse)
@app.get("/app", include_in_schema=False, response_class=HTMLResponse)
def website():
    return _page()


@app.get("/sample")
def sample_report():
    return {
        "url": "https://example.com",
        "site_name": "Illustrative sample",
        "is_sample": True,
        "policy_url": None,
        "has_cookie_banner": True,
        "has_signup_or_login": None,
        "page_request": {"method": "GET", "url": "https://example.com", "status": 200, "final_url": "https://example.com/"},
        "tracker_findings": [
            {"tracker": "Example Analytics", "domain": "analytics.example.net", "category": "Analytics", "reference_type": "script", "evidence": "Initial HTML resource reference", "occurrences": 1},
            {"tracker": "Example Ad Pixel", "domain": "ads.example.org", "category": "Advertising", "reference_type": "image", "evidence": "Initial HTML resource reference", "occurrences": 1},
        ],
        "analysis_provider": "Illustrative sample",
        "analysis": {
            "headline": "A sample privacy report layout",
            "summary": "This example shows how DataTrail explains information collection, sharing, and user choices. It is illustrative and is not a live assessment of example.com.",
            "score": 76,
            "grade": "C",
            "score_basis": "Illustrative score only. A live score is based on the policy text retrieved for the site.",
            "pillars": {
                "information_collected": "The sample policy describes account details, usage data, and device information.",
                "purpose_of_collection": "The sample policy says data supports the service, personalization, analytics, and advertising.",
                "third_party_sharing": "The sample policy names service providers and advertising partners.",
                "advertising_and_profiling": "The sample policy includes tailored advertising and an opt-out control.",
                "data_retention": "Retention periods vary by data type; some periods are not specified.",
                "international_transfers": "The sample policy allows international processing with safeguards.",
                "security_practices": "The sample policy describes encryption and access controls.",
                "user_rights_and_deletion": "The sample policy describes access, correction, deletion, and opt-out rights."
            },
            "facts": {
                "data_collected": ["Account details", "Usage history", "Device information"],
                "third_parties": ["Service providers", "Advertising partners"],
                "can_delete_account": True,
                "retention_period": "Varies by data type"
            },
            "sharing_details": [
                {"data_categories": ["Account and usage data"], "recipient": "Service providers", "purpose": "Operate and support the service", "requirement": "required_for_service", "reason": "The example policy links these providers to service delivery.", "evidence": "Illustrative sample only."},
                {"data_categories": ["Usage data"], "recipient": "Advertising partners", "purpose": "Tailored advertising", "requirement": "optional", "reason": "The example policy describes a user opt-out control.", "evidence": "Illustrative sample only."}
            ],
            "privacy_controls": [
                {"control": "Advertising opt-out", "how_to_use": "Use the privacy or advertising settings described by the site.", "evidence": "Illustrative sample only."}
            ],
            "deletion_steps": [
                {"step": "Submit a request", "detail": "Use the account privacy page or contact channel named in the policy.", "evidence": "Illustrative sample only."},
                {"step": "Verify identity", "detail": "The site may request account details to verify the request.", "evidence": "Illustrative sample only."},
                {"step": "Wait for confirmation", "detail": "Follow the site's confirmation and retention instructions.", "evidence": "Illustrative sample only."}
            ],
            "reasons": ["Illustrative sample only; not a live scan."]
        }
    }


@app.post("/scan")
def scan_website(req: ScanRequest):
    """Use TinyFish to retrieve a policy, then produce a policy-based report."""
    submitted_url = req.url.strip()
    if not submitted_url:
        raise HTTPException(status_code=422, detail="Enter a website URL.")

    url = tinyfish_agent.normalize_url(submitted_url)
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail="Enter a valid http or https website URL.")

    result = tinyfish_agent.scan_site(url)
    record = {
        "url": result.get("url") or url,
        "site_name": result.get("site_name") or parsed.hostname,
        "policy_url": result.get("policy_url"),
        "has_cookie_banner": result.get("has_cookie_banner"),
        "has_signup_or_login": result.get("has_signup_or_login"),
        "page_request": result.get("page_request"),
        "tracker_findings": result.get("tracker_findings") or [],
    }
    policy_text = result.get("policy_text")
    if not policy_text:
        record["error"] = result.get("error") or "TinyFish could not find or read a privacy policy."
        return record

    record["policy_text"] = policy_text
    analysis = result.get("policy_analysis")
    provider = "TinyFish"
    analysis_note = None

    if os.getenv("GEMINI_API_KEY"):
        try:
            analysis = analyzer.analyze(policy_text, record["tracker_findings"])
            provider = "Gemini"
        except Exception as exc:
            analysis_note = f"Gemini analysis unavailable; showing TinyFish policy analysis when available ({type(exc).__name__})."

    if isinstance(analysis, dict):
        record["analysis"] = analyzer.normalize_analysis(analysis)
        record["analysis_provider"] = provider
        if analysis_note:
            record["analysis_note"] = analysis_note
    else:
        record["analysis_note"] = "TinyFish retrieved the policy, but structured analysis was not returned. The full policy is available below."
        record["error"] = result.get("error") or "Policy analysis is unavailable."

    store.save(url, record)
    return record
