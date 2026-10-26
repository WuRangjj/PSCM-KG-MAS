"""
OA 论文快速下载 - 只从 Unpaywall OA 链接下载
跳过 Sci-Hub（被 altcha 封了）
对于非 OA 论文生成 HTML 报告供浏览器下载
"""
import re, json, time, os, subprocess
from pathlib import Path

RIS_DIR = Path(r"C:\Users\20155\dpa4_project\data\raw\ris")
PDF_DIR = Path(r"C:\Users\20155\dpa4_project\data\pdf")
OA_CACHE = Path(r"C:\Users\20155\dpa4_project\data\oa_status.json")
INDEX = Path(r"C:\Users\20155\dpa4_project\data\pdf_index.json")
REPORT = Path(r"C:\Users\20155\dpa4_project\data\download_report.html")
LOG = Path(r"C:\Users\20155\dpa4_project\data\download_log.txt")

UA = "Mozilla/5.0 (compatible; perovskite_bot; mailto:research@wzu.edu.cn)"

PDF_DIR.mkdir(parents=True, exist_ok=True)

def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    try: print(line)
    except: print(line.encode('ascii', errors='replace').decode('ascii'))
    with open(LOG, "a", encoding="utf-8") as f: f.write(line + "\n")

def curl_get(url, timeout=20):
    """GET request → bytes or None"""
    r = subprocess.run(
        ["curl", "-s", "-L", "--connect-timeout", "10", "--max-time", str(timeout),
         "-H", f"User-Agent: {UA}", url],
        capture_output=True, timeout=timeout+5,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if r.returncode == 0 and r.stdout: return r.stdout
    return None

def curl_download(url, outpath, timeout=60):
    """Download to file → (ok, size)"""
    r = subprocess.run(
        ["curl", "-s", "-L", "--connect-timeout", "10", "--max-time", str(timeout),
         "-H", f"User-Agent: {UA}", "-o", outpath, url],
        capture_output=True, timeout=timeout+10,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if r.returncode == 0 and os.path.exists(outpath):
        size = os.path.getsize(outpath)
        if size > 3000:
            with open(outpath, "rb") as f:
                if b"%PDF-" in f.read(2048):
                    return (True, size)
        if size < 5000: os.unlink(outpath)
    return (False, 0)

def find_pdf_on_page(html_bytes, base_url):
    """Extract PDF links from HTML page."""
    try:
        text = html_bytes.decode('utf-8', errors='replace')
    except:
        return []

    pdfs = []
    # Common patterns
    for m in re.finditer(r'href\s*=\s*["\']([^"\']+\.pdf[^"\'\s]*)["\']', text, re.I):
        u = m.group(1)
        if u.startswith("//"): u = "https:" + u
        elif u.startswith("/"):
            from urllib.parse import urljoin
            u = urljoin(base_url, u)
        if u not in pdfs: pdfs.append(u)

    # meta citation_pdf_url
    m = re.search(r'<meta\s+name="citation_pdf_url"\s+content="([^"]+)"', text, re.I)
    if m:
        u = m.group(1)
        if u.startswith("/"):
            from urllib.parse import urljoin
            u = urljoin(base_url, u)
        if u not in pdfs: pdfs.insert(0, u)

    return pdfs[:5]  # Max 5 URLs


# ===== Main =====

def main():
    log("=" * 50)
    log("OA PDF Fast Download")
    log("=" * 50)

    # Load OA cache
    with open(OA_CACHE, "r", encoding="utf-8") as f:
        oa_cache = json.load(f)

    # Load index
    if INDEX.exists():
        with open(INDEX, "r", encoding="utf-8") as f:
            index = json.load(f)
    else:
        index = {}

    # Parse RIS for metadata
    ris_files = sorted(RIS_DIR.glob("csp_*.ris"))
    doi_meta = {}
    for ris_file in ris_files:
        with open(ris_file, "r", encoding="utf-8") as f:
            content = f.read()
        for record in re.split(r"(?=TY  - )", content):
            if not record.strip() or not re.search(r"TY  - JOUR", record):
                continue
            dm = re.search(r"DO  - (.+)", record)
            if not dm: continue
            doi = dm.group(1).strip().replace(" ", "")
            ti = re.search(r"TI  - (.+)", record)
            py = re.search(r"PY  - (\d{4})", record)
            t2 = re.search(r"T2  - (.+)", record)
            doi_meta[doi] = {
                "doi": doi,
                "title": ti.group(1).strip() if ti else "",
                "year": py.group(1) if py else "",
                "journal": t2.group(1).strip() if t2 else "",
                "pdf_filename": doi.replace("/", "_") + ".pdf",
                "pdf_path": str(PDF_DIR / (doi.replace("/", "_") + ".pdf")),
            }

    total = len(doi_meta)
    log(f"Total papers: {total}")

    # Separate OA and non-OA
    oa_dois = [doi for doi, v in oa_cache.items() if v.get("is_oa")]
    non_oa_dois = [doi for doi, v in oa_cache.items() if not v.get("is_oa")]
    log(f"OA papers: {len(oa_dois)}, Non-OA: {len(non_oa_dois)}")

    # Count already downloaded
    already = 0
    for doi in doi_meta:
        p = Path(doi_meta[doi]["pdf_path"])
        if p.exists() and p.stat().st_size > 3000:
            with open(p, "rb") as f:
                if b"%PDF-" in f.read(2048):
                    already += 1
                    if doi not in index:
                        index[doi] = {**doi_meta[doi], "status": "downloaded", "source": "already", "file_size_kb": round(p.stat().st_size/1024,1)}
    log(f"Already downloaded: {already}")

    # Build pending list (OA only, not yet downloaded)
    pending = []
    for doi in oa_dois:
        if doi not in doi_meta: continue
        p = Path(doi_meta[doi]["pdf_path"])
        if p.exists() and p.stat().st_size > 3000:
            with open(p, "rb") as f:
                if b"%PDF-" in f.read(2048): continue
        pending.append(doi)

    log(f"OA pending: {len(pending)}")

    # Download OA papers
    ok, fail = 0, 0
    for i, doi in enumerate(pending):
        meta = doi_meta[doi]
        oa_info = oa_cache.get(doi, {})
        urls = oa_info.get("pdf_urls", [])
        title_s = meta["title"][:80]

        log(f"\n[{i+1}/{len(pending)}] {doi}")
        log(f"  {title_s} (OA)")

        downloaded = False
        for url in urls:
            # Direct PDF?
            if url.lower().endswith('.pdf') or '/pdf/' in url.lower():
                ok_flag, size = curl_download(url, meta["pdf_path"], timeout=60)
                if ok_flag:
                    log(f"  OK direct PDF ({size//1024}KB)")
                    index[doi] = {**meta, "status": "downloaded", "source": "oa_direct", "file_size_kb": round(size/1024,1)}
                    ok += 1; downloaded = True
                    break

            # Landing page → find PDF links
            html = curl_get(url, timeout=15)
            if html:
                pdf_links = find_pdf_on_page(html, url)
                for pl in pdf_links:
                    ok_flag, size = curl_download(pl, meta["pdf_path"], timeout=45)
                    if ok_flag:
                        log(f"  OK via page parse ({size//1024}KB)")
                        index[doi] = {**meta, "status": "downloaded", "source": "oa_page", "file_size_kb": round(size/1024,1)}
                        ok += 1; downloaded = True
                        break
                if downloaded: break

        if not downloaded:
            log(f"  FAILED (OA but unreachable)")
            index[doi] = {**meta, "status": "failed"}
            fail += 1

        # Save every 10
        if (i+1) % 10 == 0:
            with open(INDEX, "w", encoding="utf-8") as f:
                json.dump(index, f, ensure_ascii=False, indent=2)
            log(f"  --- Progress: {i+1}/{len(pending)} OK={ok} FAIL={fail} ---")

        time.sleep(0.5)  # Small delay

    # Final save
    with open(INDEX, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    # ===== Generate HTML Report =====
    non_downloaded = []
    for doi, meta in doi_meta.items():
        if doi in index and index[doi].get("status") == "downloaded":
            continue
        oa_info = oa_cache.get(doi, {})
        non_downloaded.append({
            **meta,
            "is_oa": oa_info.get("is_oa", False),
            "oa_urls": oa_info.get("pdf_urls", []),
            "doi_url": f"https://doi.org/{doi}",
            "scihub": f"https://sci-hub.st/{doi}",
            "proxy": f"https://doi-org-s.webvpn.wzu.edu.cn/{doi}",
        })

    html = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="UTF-8"><title>下载报告</title>
<style>
body{{font-family:Arial,sans-serif;max-width:1100px;margin:20px auto;padding:20px;background:#f5f5f5}}
h1{{color:#333}}.stats{{background:#fff;padding:15px;border-radius:8px;margin:10px 0;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
table{{width:100%;border-collapse:collapse;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.1);font-size:13px}}
th{{background:#4a90d9;color:white;padding:8px 10px;text-align:left;position:sticky;top:0}}
td{{padding:6px 10px;border-bottom:1px solid #eee}}tr:hover{{background:#f0f7ff}}
a{{color:#4a90d9;text-decoration:none;margin-right:6px}}a:hover{{text-decoration:underline}}
.badge{{padding:2px 6px;border-radius:8px;font-size:10px}}
.oa{{background:#d4edda;color:#155724}}.closed{{background:#f8d7da;color:#721c24}}
</style></head><body>
<h1>Perovskite PDF Download Report</h1>
<div class="stats">
<p>Total: <b>{total}</b> | Downloaded: <b>{total-len(non_downloaded)}</b> ({100*(total-len(non_downloaded))//total}%) | Remaining: <b>{len(non_downloaded)}</b></p>
<p>Open this page in your browser (where you're logged into WZU WebVPN). Click <b style="color:#27ae60">Proxy</b> links to download via institutional access.</p>
</div>
<table><thead><tr><th>#</th><th>Title</th><th>Year</th><th>OA</th><th>Links</th></tr></thead><tbody>
"""
    for i, item in enumerate(non_downloaded, 1):
        badge = '<span class="badge oa">OA</span>' if item["is_oa"] else '<span class="badge closed">paywall</span>'
        links = f'<a href="{item["doi_url"]}" target="_blank">DOI</a>'
        links += f' <a href="{item["proxy"]}" target="_blank" style="color:#27ae60">Proxy</a>'
        links += f' <a href="{item["scihub"]}" target="_blank" style="color:#e74c3c">SciHub</a>'
        for j, u in enumerate(item["oa_urls"][:2]):
            links += f' <a href="{u}" target="_blank" style="color:#f39c12">OA{j+1}</a>'
        html += f'<tr><td>{i}</td><td>{item["title"][:120]}</td><td>{item["year"]}</td><td>{badge}</td><td>{links}</td></tr>\n'

    html += f"</tbody></table><p style='color:#888;margin-top:20px'>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')} | {len(non_downloaded)} papers to download</p></body></html>"

    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(html)

    total_ok = sum(1 for v in index.values() if v.get("status") == "downloaded")
    log(f"\n{'='*50}")
    log(f"DONE! Downloaded: {total_ok}/{total}")
    log(f"  Index: {INDEX}")
    log(f"  Report: {REPORT} (open in browser for remaining {total-total_ok} papers)")
    log(f"{'='*50}")


if __name__ == "__main__":
    main()
