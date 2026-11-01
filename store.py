import json
import difflib
from pathlib import Path
from urllib.parse import urlparse

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

def site_key(url: str) -> str:
    parsed = urlparse(url)
    domain = parsed.netloc or parsed.path
    return domain.replace("www.", "").replace("/", "_")

def store_path(url: str) -> Path:
    return DATA_DIR / f"{site_key(url)}.json"

def load(url: str) -> dict | None:
    path = store_path(url)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

def save(url: str, record: dict):
    path = store_path(url)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")

def diff_policies(old_text: str, new_text: str) -> dict:
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()

    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=""))
    added = [line[1:] for line in diff if line.startswith("+") and not line.startswith("++")]
    removed = [line[1:] for line in diff if line.startswith("-") and not line.startswith("--")]

    changed = len(added) > 0 or len(removed) > 0
    return {
        "changed": changed,
        "added": added,
        "removed": removed
    }