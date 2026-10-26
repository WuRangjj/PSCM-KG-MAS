"""
Step 1: Check OA status for all DOIs via Unpaywall
Generates: oa_status.json with OA info for all papers
"""
import re
import json
import time
import subprocess
import os
from pathlib import Path

RIS_DIR = Path(r"C:\Users\20155\dpa4_project\data\raw\ris")
OUTPUT = Path(r"C:\Users\20155\dpa4_project\data\oa_status.json")
UA = "Mozilla/5.0 (compatible; perovskite_bot/1.0; mailto:research@wzu.edu.cn)"

def curl_json(url, timeout=30):
    result = subprocess.run(
        ["curl", "-s", "-L", "--connect-timeout", "15", "--max-time", str(timeout),
         "-H", f"User-Agent: {UA}", url],
        capture_output=True, timeout=timeout+5,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
    )
    if result.returncode == 0 and result.stdout:
        try:
            return json.loads(result.stdout.decode('utf-8'))
        except:
            pass
    return None

# Step 1: Extract all DOIs
def parse_all_dois():
    ris_files = sorted(RIS_DIR.glob("csp_*.ris"))
    dois = []
    for ris_file in ris_files:
        with open(ris_file, "r", encoding="utf-8") as f:
            content = f.read()
        records = re.split(r"(?=TY  - )", content)
        for record in records:
            if not record.strip() or not re.search(r"TY  - JOUR", record):
                continue
            doi_match = re.search(r"DO  - (.+)", record)
            if doi_match:
                doi = doi_match.group(1).strip().replace(" ", "")
                dois.append(doi)
    return dois

print("Extracting DOIs...")
dois = parse_all_dois()
print(f"Found {len(dois)} DOIs")

# Step 2: Check OA status
if OUTPUT.exists():
    with open(OUTPUT, "r", encoding="utf-8") as f:
        results = json.load(f)
    print(f"Loaded {len(results)} existing results")
else:
    results = {}

new_count = 0
for i, doi in enumerate(dois):
    if doi in results:
        continue

    url = f"https://api.unpaywall.org/v2/{doi}?email=perovskite_project@wzu.edu.cn"
    data = curl_json(url)

    if data:
        results[doi] = {
            "is_oa": data.get("is_oa", False),
            "oa_status": data.get("oa_status", "closed"),
            "title": data.get("title", "")[:100],
            "journal": data.get("journal_name", ""),
            "year": data.get("year", ""),
            "pdf_url": None,
            "landing_url": None,
        }
        if data.get("is_oa"):
            best = data.get("best_oa_location", {})
            results[doi]["pdf_url"] = best.get("url_for_pdf") or best.get("url")
            results[doi]["landing_url"] = best.get("url_for_landing_page")
            # Also collect all OA locations
            oa_urls = []
            for loc in data.get("oa_locations", []):
                u = loc.get("url_for_pdf") or loc.get("url")
                if u:
                    oa_urls.append(u)
            results[doi]["all_oa_urls"] = oa_urls
        new_count += 1

    if (i+1) % 10 == 0:
        print(f"  Progress: {i+1}/{len(dois)} (new: {new_count})")
        with open(OUTPUT, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

    time.sleep(0.3)  # Rate limit: ~3 requests/sec (Unpaywall free tier: 100k/day)

# Save final
with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

# Stats
oa_count = sum(1 for v in results.values() if v.get("is_oa"))
print(f"\nDone! Total: {len(results)}, OA: {oa_count}, Non-OA: {len(results)-oa_count}")
print(f"OA Rate: {oa_count/len(results)*100:.1f}%")
print(f"Saved to: {OUTPUT}")
