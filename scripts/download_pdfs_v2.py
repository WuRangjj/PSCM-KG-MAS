"""
钙钛矿文献 PDF 批量下载 V2 - 多策略综合方案
=============================================

策略优先级:
1. Unpaywall OA PDF → 直接下载（免费合法）
2. Sci-Hub 页面解析 → 获取 storage URL → 下载（间隔+重试）
3. 生成浏览器下载 HTML（用户手动下载，机构权限）

输出:
- data/pdf/            → PDF 文件（DOI命名）
- data/pdf_index.json  → DOI → 元数据映射
- data/download_report.html → 下载报告 + 浏览器下载链接
"""

import re
import json
import time
import os
import subprocess
import random
from pathlib import Path

# ===== 配置 =====
RIS_DIR = Path(r"C:\Users\20155\dpa4_project\data\raw\ris")
PDF_DIR = Path(r"C:\Users\20155\dpa4_project\data\pdf")
INDEX_FILE = Path(r"C:\Users\20155\dpa4_project\data\pdf_index.json")
OA_CACHE = Path(r"C:\Users\20155\dpa4_project\data\oa_status.json")
HTML_REPORT = Path(r"C:\Users\20155\dpa4_project\data\download_report.html")
LOG_FILE = Path(r"C:\Users\20155\dpa4_project\data\download_log.txt")

UNPAYWALL_EMAIL = "perovskite@wzu.edu.cn"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

SCI_HUB_MIRRORS = [
    "https://sci-hub.st",
    "https://sci-hub.ru",
]

DL_TIMEOUT = 90
BATCH_SIZE = 50  # 每批下载多少篇

PDF_DIR.mkdir(parents=True, exist_ok=True)


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    try: print(line)
    except: print(line.encode('ascii', errors='replace').decode('ascii'))
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def curl_bytes(url, timeout=30, referer=None):
    """Run curl, return bytes or None."""
    cmd = ["curl", "-s", "-L", "--connect-timeout", "12", "--max-time", str(timeout),
           "-H", f"User-Agent: {UA}"]
    if referer:
        cmd += ["-H", f"Referer: {referer}"]
    cmd.append(url)
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout+10,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if r.returncode == 0 and r.stdout:
            return r.stdout
        return None
    except:
        return None


def curl_download(url, outpath, referer=None):
    """Download to file, return (success, size_bytes)."""
    cmd = ["curl", "-s", "-L", "--connect-timeout", "12", "--max-time", str(DL_TIMEOUT),
           "-H", f"User-Agent: {UA}", "-o", outpath]
    if referer:
        cmd += ["-H", f"Referer: {referer}"]
    cmd.append(url)
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=DL_TIMEOUT+10,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if r.returncode == 0 and os.path.exists(outpath):
            size = os.path.getsize(outpath)
            if size > 3000:
                with open(outpath, "rb") as f:
                    header = f.read(5)
                if header == b"%PDF-":
                    return (True, size)
                # Also check for PDF magic elsewhere in first 2KB
                with open(outpath, "rb") as f:
                    if b"%PDF-" in f.read(2048):
                        return (True, size)
            # Clean up junk
            if size < 3000:
                os.unlink(outpath)
        return (False, 0)
    except:
        return (False, 0)


# ===== Step 1: Parse RIS & Extract Metadata =====

def parse_all_ris():
    """Parse RIS files → {DOI: metadata}"""
    ris_files = sorted(RIS_DIR.glob("csp_*.ris"))
    log(f"Parsing {len(ris_files)} RIS files...")

    doi_map = {}
    for ris_file in ris_files:
        with open(ris_file, "r", encoding="utf-8") as f:
            content = f.read()

        for record in re.split(r"(?=TY  - )", content):
            if not record.strip() or not re.search(r"TY  - JOUR", record):
                continue

            dm = re.search(r"DO  - (.+)", record)
            if not dm:
                continue
            doi = dm.group(1).strip().replace(" ", "")

            ti = re.search(r"TI  - (.+)", record)
            title = ti.group(1).strip() if ti else ""

            au = [a.strip() for a in re.findall(r"AU  - (.+)", record)]

            py = re.search(r"PY  - (\d{4})", record)
            year = py.group(1) if py else ""

            t2 = re.search(r"T2  - (.+)", record)
            journal = t2.group(1).strip() if t2 else ""

            nc = re.search(r"Times Cited[^\d]*(\d+)", record)
            cited = int(nc.group(1)) if nc else 0

            pdf_fn = doi.replace("/", "_") + ".pdf"

            doi_map[doi] = {
                "doi": doi,
                "title": title,
                "authors": au,
                "year": year,
                "journal": journal,
                "times_cited": cited,
                "pdf_filename": pdf_fn,
                "pdf_path": str(PDF_DIR / pdf_fn),
                "ris_source": ris_file.name,
            }

    log(f"Parsed {len(doi_map)} papers with DOI")
    return doi_map


# ===== Step 2: OA Detection via Unpaywall =====

def cache_oa_status(doi_map):
    """Check Unpaywall for all uncached DOIs."""
    if OA_CACHE.exists():
        with open(OA_CACHE, "r", encoding="utf-8") as f:
            cache = json.load(f)
    else:
        cache = {}

    new = 0
    dois = list(doi_map.keys())
    for i, doi in enumerate(dois):
        if doi in cache:
            continue

        url = f"https://api.unpaywall.org/v2/{doi}?email={UNPAYWALL_EMAIL}"
        data = curl_bytes(url, timeout=20)
        if data:
            try:
                d = json.loads(data.decode('utf-8'))
                cache[doi] = {
                    "is_oa": d.get("is_oa", False),
                    "oa_status": d.get("oa_status", "closed"),
                    "title": d.get("title", "")[:100],
                    "journal": d.get("journal_name", ""),
                    "year": d.get("year", ""),
                    "pdf_urls": [],
                }
                if d.get("is_oa"):
                    for loc in d.get("oa_locations", []):
                        u = loc.get("url_for_pdf") or loc.get("url")
                        if u:
                            cache[doi]["pdf_urls"].append(u)
                new += 1
            except:
                pass

        if (i+1) % 20 == 0:
            log(f"  Unpaywall check: {i+1}/{len(dois)} (new: {new})")
            with open(OA_CACHE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)

        time.sleep(0.25)

    with open(OA_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    oa = sum(1 for v in cache.values() if v.get("is_oa"))
    log(f"OA check done: {oa} OA out of {len(cache)}")
    return cache


# ===== Step 3: Sci-Hub PDF URL extraction =====

def scihub_find_pdf(doi):
    """Visit Sci-Hub page, extract PDF URL."""
    for mirror in SCI_HUB_MIRRORS:
        html = curl_bytes(f"{mirror}/{doi}", timeout=25)
        if not html or len(html) < 500:
            continue

        try:
            text = html.decode('utf-8', errors='replace')
        except:
            continue

        # citation_pdf_url meta
        m = re.search(r'<meta\s+name="citation_pdf_url"\s+content="([^"]+)"', text, re.I)
        if m:
            path = m.group(1)
            if path.startswith("/"):
                return mirror + path
            return path

        # iframe/embed
        m = re.search(r'(?:iframe|embed)\s+[^>]*?src\s*=\s*["\']([^"\']+\.pdf[^"\']*)["\']', text, re.I)
        if m:
            u = m.group(1)
            if u.startswith("//"): u = "https:" + u
            elif u.startswith("/"): u = mirror.rstrip("/") + u
            return u

    return None


# ===== Step 4: Download =====

def download_one(doi, meta, oa_cache):
    """Try all strategies for one paper. Returns (status, source)."""
    pdf_path = Path(meta["pdf_path"])

    # Already done?
    if pdf_path.exists() and pdf_path.stat().st_size > 3000:
        with open(pdf_path, "rb") as f:
            if b"%PDF-" in f.read(2048):
                return ("already", pdf_path.stat().st_size)

    oa_info = oa_cache.get(doi, {})

    # Strategy 1: Unpaywall OA URLs
    for oa_url in oa_info.get("pdf_urls", []):
        ok, size = curl_download(oa_url, str(pdf_path))
        if ok:
            return ("oa", size)
        time.sleep(0.5)

    # Strategy 2: Sci-Hub
    sci_url = scihub_find_pdf(doi)
    if sci_url:
        ok, size = curl_download(sci_url, str(pdf_path),
                                 referer=f"{SCI_HUB_MIRRORS[0]}/{doi}")
        if ok:
            return ("scihub", size)

        # Also try direct download
        for mirror in SCI_HUB_MIRRORS:
            ok, size = curl_download(f"{mirror}/download/{doi}", str(pdf_path),
                                     referer=f"{mirror}/{doi}")
            if ok:
                return ("scihub_direct", size)
            time.sleep(1)

    return ("failed", 0)


# ===== Step 5: HTML Report =====

def generate_html_report(doi_map, index, oa_cache):
    """Generate browser-downloadable HTML for failed papers."""
    total = len(doi_map)
    ok = sum(1 for v in index.values() if v.get("status") in ("downloaded", "already"))
    failed_items = []

    for doi, meta in doi_map.items():
        if doi in index and index[doi].get("status") in ("downloaded", "already"):
            continue
        oa_info = oa_cache.get(doi, {})
        failed_items.append({
            "doi": doi,
            "title": meta["title"],
            "journal": meta["journal"],
            "year": meta["year"],
            "is_oa": oa_info.get("is_oa", False),
            "oa_urls": oa_info.get("pdf_urls", []),
            "doi_url": f"https://doi.org/{doi}",
            "scihub_url": f"https://sci-hub.st/{doi}",
            "proxy_url": f"https://doi-org-s.webvpn.wzu.edu.cn/{doi}",
        })

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>钙钛矿文献 PDF 下载报告</title>
<style>
body {{ font-family: 'Segoe UI', Arial, sans-serif; max-width: 1000px; margin: 20px auto; padding: 20px; background: #f5f5f5; }}
h1 {{ color: #333; }} .stats {{ background: #fff; padding: 15px; border-radius: 8px; margin: 10px 0; box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
table {{ width: 100%; border-collapse: collapse; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
th {{ background: #4a90d9; color: white; padding: 10px; text-align: left; position: sticky; top: 0; }}
td {{ padding: 8px 10px; border-bottom: 1px solid #eee; font-size: 13px; }}
tr:hover {{ background: #f0f7ff; }}
a {{ color: #4a90d9; text-decoration: none; margin-right: 8px; }}
a:hover {{ text-decoration: underline; }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; }}
.badge-oa {{ background: #d4edda; color: #155724; }}
.badge-closed {{ background: #f8d7da; color: #721c24; }}
.progress {{ height: 20px; background: #e0e0e0; border-radius: 10px; margin: 10px 0; overflow: hidden; }}
.progress-bar {{ height: 100%; background: #4caf50; }}
</style>
</head>
<body>

<h1>🔬 钙钛矿文献 PDF 下载报告</h1>

<div class="stats">
<h3>📊 统计</h3>
<p>总文献数: <strong>{total}</strong></p>
<p>✅ 已下载: <strong>{ok}</strong> ({ok/total*100:.1f}%)</p>
<p>❌ 未下载: <strong>{total - ok}</strong> ({(total-ok)/total*100:.1f}%)</p>
<div class="progress"><div class="progress-bar" style="width:{ok/total*100:.1f}%"></div></div>
</div>

<div class="stats">
<h3>🔗 未下载文献列表（点击链接在浏览器中下载）</h3>
<p>你已通过学校登录 WZU WebVPN，点击 <strong>proxy</strong> 链接可以通过机构权限下载。</p>
<p>链接类型: <a style="color:#4a90d9">DOI</a> = 出版社页面 |
<a style="color:#e74c3c">Sci-Hub</a> = 免费下载 |
<a style="color:#27ae60">Proxy</a> = 学校代理（推荐） |
<a style="color:#f39c12">OA</a> = 开放获取</p>
</div>

<table>
<thead>
<tr><th>#</th><th>标题</th><th>期刊</th><th>年份</th><th>OA</th><th>下载链接</th></tr>
</thead>
<tbody>
"""

    for i, item in enumerate(failed_items, 1):
        oa_badge = '<span class="badge badge-oa">OA</span>' if item["is_oa"] else '<span class="badge badge-closed">付费</span>'
        links = f'<a href="{item["doi_url"]}" target="_blank" title="出版社页面">DOI</a>'
        links += f' <a href="{item["proxy_url"]}" target="_blank" title="学校代理" style="color:#27ae60">Proxy</a>'
        links += f' <a href="{item["scihub_url"]}" target="_blank" title="Sci-Hub" style="color:#e74c3c">Sci-Hub</a>'
        for j, oa_u in enumerate(item["oa_urls"][:2]):
            links += f' <a href="{oa_u}" target="_blank" title="Open Access PDF" style="color:#f39c12">OA{j+1}</a>'

        html += f"""<tr>
<td>{i}</td>
<td style="max-width:400px">{item["title"][:120]}</td>
<td>{item["journal"][:30]}</td>
<td>{item["year"]}</td>
<td>{oa_badge}</td>
<td>{links}</td>
</tr>
"""

    html += f"""
</tbody>
</table>

<p style="color:#888; margin-top:20px">生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')} | 共 {len(failed_items)} 篇待下载</p>

<script>
// 自动计数
document.addEventListener('DOMContentLoaded', function() {{
    console.log('待下载: {len(failed_items)} 篇');
    console.log('建议在浏览器中使用 DownThemAll 或类似扩展批量下载');
}});
</script>

</body>
</html>"""

    with open(HTML_REPORT, "w", encoding="utf-8") as f:
        f.write(html)
    log(f"HTML report saved to: {HTML_REPORT}")


# ===== Main =====

def main():
    log("=" * 60)
    log("Perovskite PDF Download V2 - Multi-strategy")
    log("=" * 60)

    # 1. Parse
    doi_map = parse_all_ris()

    # 2. OA cache
    log("Checking OA status...")
    oa_cache = cache_oa_status(doi_map)

    # 3. Load existing index
    if INDEX_FILE.exists():
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            index = json.load(f)
    else:
        index = {}

    # 4. Count already done
    already = 0
    for doi, meta in doi_map.items():
        p = Path(meta["pdf_path"])
        if p.exists() and p.stat().st_size > 3000:
            with open(p, "rb") as f:
                if b"%PDF-" in f.read(2048):
                    already += 1
                    if doi not in index:
                        index[doi] = meta
                        index[doi]["status"] = "already"
                        index[doi]["file_size_kb"] = round(p.stat().st_size / 1024, 1)

    # Save initial index
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    log(f"Already downloaded: {already} / {len(doi_map)}")

    # 5. Build pending list
    pending = []
    for doi, meta in doi_map.items():
        p = Path(meta["pdf_path"])
        if p.exists() and p.stat().st_size > 3000:
            with open(p, "rb") as f:
                if b"%PDF-" in f.read(2048):
                    continue
        pending.append((doi, meta))

    log(f"Pending: {len(pending)}")

    # 6. Download in batches
    ok, fail = 0, 0
    for i, (doi, meta) in enumerate(pending):
        title_s = (meta["title"] or "(untitled)")[:80]
        log(f"\n[{i+1}/{len(pending)}] {doi}")
        log(f"  {title_s}")

        status, size = download_one(doi, meta, oa_cache)

        if status in ("oa", "scihub", "scihub_direct"):
            meta["status"] = "downloaded"
            meta["source"] = status
            meta["file_size_kb"] = round(size / 1024, 1)
            index[doi] = meta
            log(f"  OK [{status}] ({meta['file_size_kb']} KB)")
            ok += 1
        elif status == "already":
            meta["status"] = "already"
            meta["file_size_kb"] = round(size / 1024, 1)
            index[doi] = meta
            log(f"  Already ({meta['file_size_kb']} KB)")
            ok += 1
        else:
            index[doi] = meta
            index[doi]["status"] = "failed"
            log(f"  FAILED")
            fail += 1

        # Save periodically
        if (i+1) % 20 == 0:
            with open(INDEX_FILE, "w", encoding="utf-8") as f:
                json.dump(index, f, ensure_ascii=False, indent=2)
            log(f"\n--- Progress: {i+1}/{len(pending)}, OK={ok}, FAIL={fail} ---")

        # Delay between downloads
        delay = random.uniform(1.5, 3.0)
        if status in ("scihub", "scihub_direct"):
            delay = random.uniform(3.0, 6.0)  # Longer delay after Sci-Hub
        if i < len(pending) - 1:
            time.sleep(delay)

    # 7. Final save
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    # 8. Generate HTML report
    generate_html_report(doi_map, index, oa_cache)

    total_ok = sum(1 for v in index.values() if v.get("status") in ("downloaded", "already"))
    log("\n" + "=" * 60)
    log(f"FINAL: {total_ok}/{len(doi_map)} downloaded")
    log(f"  PDF dir: {PDF_DIR}")
    log(f"  Index: {INDEX_FILE}")
    log(f"  Report: {HTML_REPORT}")
    log("=" * 60)


if __name__ == "__main__":
    main()
