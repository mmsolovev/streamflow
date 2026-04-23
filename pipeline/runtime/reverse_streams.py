import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STREAMS_FILE = ROOT / "storage" / "streams.json"


streams = json.loads(STREAMS_FILE.read_text(encoding="utf-8"))

# разворачиваем список
streams.reverse()

STREAMS_FILE.write_text(json.dumps(streams, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print("streams.json reversed")
