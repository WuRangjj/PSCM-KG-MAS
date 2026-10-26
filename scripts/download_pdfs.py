"""
钙钛矿文献 PDF 批量下载脚本 (curl-based)
==========================================
策略（多源优先级）:
1. Unpaywall API → 获取 OA PDF 直链（免费合法）
2. Sci-Hub → 解析页面获取 PDF 直链
3. 全部用 curl 子进程执行（避免 Python DNS 问题）

DOI 是连接 PDF 和 RIS 元数据的唯一桥梁
PDF 文件名: {DOI.replace('/', '_')}.pdf
"""

import os
import re
import json
import time
import subprocess
import tempfile
import shutil
from pathlib import Path

# ========== 配置 ==========
RIS_DIR = Path(r"C:\Users\20155\dpa4_project\data\raw\ris")
PDF_DIR = Path(r"C:\Users\20155\dpa4_project\data\pdf")
INDEX_FILE = Path(r"C:\Users\20155\dpa4_project\data\pdf_index.json")
FAILED_FILE = Path(r"C:\Users\20155\dpa4_project\data\pdf_failed.json")
LOG_FILE = Path(r"C:\Users\20155\dpa4_project\data\pdf_download_log.txt")

UNPAYWALL_EMAIL = "perovskite_project@wzu.edu.cn"  # 换成你的邮箱

# Sci-Hub 域名（按优先级）
SCI_HUB_DOMAINS = [
    "https://sci-hub.ru",
    "https://sci-hub.st",
]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

CURL_TIMEOUT = 60
SLEEP_BETWEEN = 1.5  # 篇间休息
RETRY_TIMES = 3

PDF_DIR.mkdir(parents=True, exist_ok=True)


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode('ascii', errors='replace').decode('ascii'))
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def curl_cmd(args: list, timeout: int = CURL_TIMEOUT) -> subprocess.CompletedProcess:
    """Run curl with standard args. Returns result with stdout as string (UTF-8)."""
    base = [
        "curl", "-s", "-L",
        "--connect-timeout", "15",
        "--max-time", str(timeout),
        "-H", f"User-Agent: {UA}",
    ]
    full_cmd = base + args
    try:
        return subprocess.run(
            full_cmd,
            capture_output=True,
            timeout=timeout + 10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(full_cmd, -1, b"", b"timeout")
    except Exception as e:
        return subprocess.CompletedProcess(full_cmd, -1, b"", str(e).encode())


def curl_download(url: str, output_path: str, referer: str = "") -> bool:
    """Download file via curl. Returns True if success."""
    cmd = [
        "curl", "-s", "-L",
        "--connect-timeout", "15",
        "--max-time", "120",
        "-H", f"User-Agent: {UA}",
        "-o", output_path,
    ]
    if referer:
        cmd += ["-H", f"Referer: {referer}"]
    cmd.append(url)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True,
            timeout=130,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
        )
        if result.returncode == 0 and os.path.exists(output_path):
            size = os.path.getsize(output_path)
            if size > 2000:  # At least 2KB
                with open(output_path, "rb") as f:
                    header = f.read(5)
                if header == b"%PDF-":
                    return True
                else:
                    log(f"  Not PDF (header={header[:20]}), deleting {size} bytes")
        # Clean up failed download
        if os.path.exists(output_path) and os.path.getsize(output_path) < 2000:
            os.unlink(output_path)
        return False
    except Exception as e:
        log(f"  curl download error: {e}")
        return False


def check_unpaywall(doi: str) -> str | None:
    """Query Unpaywall API. Returns PDF URL if OA, else None."""
    url = f"https://api.unpaywall.org/v2/{doi}?email={UNPAYWALL_EMAIL}"
    result = curl_cmd([url])

    if result.returncode != 0 or not result.stdout:
        return None

    try:
        data = json.loads(result.stdout.decode('utf-8'))
        if data.get("is_oa"):
            best = data.get("best_oa_location", {})
            pdf_url = best.get("url_for_pdf") or best.get("url")
            if pdf_url:
                return pdf_url  # url_for_pdf is more reliable
            # Also try oa_locations
            for loc in data.get("oa_locations", []):
                u = loc.get("url_for_pdf") or loc.get("url")
                if u:
                    return u
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    return None


def scihub_get_pdf_url(doi: str) -> tuple[str | None, str | None]:
    """
    Access Sci-Hub page and extract PDF URL.
    Returns (pdf_url, domain) or (None, None).
    """
    for domain in SCI_HUB_DOMAINS:
        url = f"{domain}/{doi}"
        result = curl_cmd([url])

        if result.returncode != 0 or not result.stdout:
            continue
        try:
            html = result.stdout.decode('utf-8', errors='replace')
        except:
            continue

        if len(html) < 500:
            continue

        # Pattern 1: citation_pdf_url meta tag (new Sci-Hub)
        match = re.search(
            r'<meta\s+name="citation_pdf_url"\s+content="([^"]+)"',
            html, re.IGNORECASE
        )
        if match:
            pdf_path = match.group(1)
            if pdf_path.startswith("/"):
                pdf_url = domain + pdf_path
            else:
                pdf_url = pdf_path
            return (pdf_url, domain)

        # Pattern 2: iframe/embed with .pdf
        match = re.search(
            r'(?:iframe|embed)\s+[^>]*?src\s*=\s*["\']([^"\']+\.pdf[^"\']*)["\']',
            html, re.IGNORECASE
        )
        if match:
            pdf_url = match.group(1)
            if pdf_url.startswith("//"):
                pdf_url = "https:" + pdf_url
            elif pdf_url.startswith("/"):
                pdf_url = domain.rstrip("/") + "/" + pdf_url.lstrip("/")
            return (pdf_url, domain)

        # Pattern 3: button/location.href
        match = re.search(
            r"""location\.href\s*=\s*['"]([^'"]+\.pdf[^'"]*)['"]""",
            html, re.IGNORECASE
        )
        if match:
            pdf_url = match.group(1)
            if pdf_url.startswith("//"):
                pdf_url = "https:" + pdf_url
            elif pdf_url.startswith("/"):
                pdf_url = domain.rstrip("/") + "/" + pdf_url.lstrip("/")
            return (pdf_url, domain)

        # Pattern 4: Any href with .pdf
        match = re.search(
            r'href\s*=\s*["\']([^"\']+\.pdf[^"\'\s]*)["\']',
            html, re.IGNORECASE
        )
        if match:
            pdf_url = match.group(1)
            if pdf_url.startswith("//"):
                pdf_url = "https:" + pdf_url
            elif pdf_url.startswith("/"):
                pdf_url = domain.rstrip("/") + "/" + pdf_url.lstrip("/")
            return (pdf_url, domain)

    return (None, None)


def download_pdf(doi: str, pdf_path: Path) -> bool:
    """
    Download PDF for a DOI. Multi-source strategy.
    Returns True on success.
    """
    # Strategy 1: Unpaywall OA
    log(f"  Trying Unpaywall...")
    oa_url = check_unpaywall(doi)
    if oa_url:
        log(f"  OA URL: {oa_url[:100]}...")
        if curl_download(oa_url, str(pdf_path)):
            log(f"  OK via Unpaywall ({pdf_path.stat().st_size//1024}KB)")
            return True
        log(f"  OA download failed, trying Sci-Hub...")

    # Strategy 2: Sci-Hub
    sci_url, sci_domain = scihub_get_pdf_url(doi)
    if sci_url:
        log(f"  Sci-Hub PDF: {sci_url[:100]}...")
        if curl_download(sci_url, str(pdf_path), referer=f"{sci_domain}/{doi}"):
            log(f"  OK via Sci-Hub ({pdf_path.stat().st_size//1024}KB)")
            return True

    # Strategy 3: Sci-Hub direct download endpoint
    for domain in SCI_HUB_DOMAINS:
        direct = f"{domain}/download/{doi}"
        log(f"  Trying direct: {direct}")
        if curl_download(direct, str(pdf_path), referer=f"{domain}/{doi}"):
            log(f"  OK via direct ({pdf_path.stat().st_size//1024}KB)")
            return True

    return False


def parse_all_ris() -> dict:
    """Parse all RIS files, return {DOI: metadata}."""
    ris_files = sorted(RIS_DIR.glob("csp_*.ris"))
    log(f"Found {len(ris_files)} RIS files")

    doi_map = {}
    total = 0

    for ris_file in ris_files:
        with open(ris_file, "r", encoding="utf-8") as f:
            content = f.read()

        records = re.split(r"(?=TY  - )", content)

        for record in records:
            if not record.strip() or not re.search(r"TY  - JOUR", record):
                continue
            total += 1

            doi_match = re.search(r"DO  - (.+)", record)
            if not doi_match:
                continue
            doi = doi_match.group(1).strip()
            doi = re.sub(r"\s+", "", doi)

            ti_match = re.search(r"TI  - (.+)", record)
            title = ti_match.group(1).strip() if ti_match else ""

            authors = [au.strip() for au in re.findall(r"AU  - (.+)", record)]

            py_match = re.search(r"PY  - (\d{4})", record)
            year = py_match.group(1) if py_match else ""

            t2_match = re.search(r"T2  - (.+)", record)
            journal = t2_match.group(1).strip() if t2_match else ""

            cited = 0
            n1_match = re.search(r"Times Cited[^\d]*(\d+)", record)
            if n1_match:
                cited = int(n1_match.group(1))

            pdf_filename = doi.replace("/", "_") + ".pdf"

            doi_map[doi] = {
                "doi": doi,
                "title": title,
                "authors": authors,
                "year": year,
                "journal": journal,
                "times_cited": cited,
                "pdf_filename": pdf_filename,
                "pdf_path": str(PDF_DIR / pdf_filename),
                "ris_source": ris_file.name,
            }

    log(f"Parsed {total} entries, {len(doi_map)} with DOI")
    return doi_map


def load_json(path: Path) -> dict:
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_json(path: Path, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main(start: int = 0, max_dl: int | None = None, retry_failed: bool = False):
    log("=" * 60)
    log("Perovskite PDF Batch Download (curl multi-source)")
    log("=" * 60)

    doi_map = parse_all_ris()

    # Load state
    index = load_json(INDEX_FILE)
    failed = load_json(FAILED_FILE)

    if retry_failed:
        failed = {}
        save_json(FAILED_FILE, failed)
        log("Cleared failed list.")

    # Count already downloaded
    existing = 0
    for doi, meta in doi_map.items():
        p = Path(meta["pdf_path"])
        if p.exists() and p.stat().st_size > 2000:
            existing += 1
            if doi not in index:
                index[doi] = meta
                index[doi]["status"] = "downloaded"
                index[doi]["file_size_kb"] = round(p.stat().st_size / 1024, 1)

    save_json(INDEX_FILE, index)
    log(f"Already downloaded: {existing} / {len(doi_map)}")

    # Build download list
    to_dl = []
    for doi, meta in doi_map.items():
        p = Path(meta["pdf_path"])
        if p.exists() and p.stat().st_size > 2000:
            continue
        if doi in failed and failed[doi].get("retries", 0) >= 9:
            continue
        to_dl.append((doi, meta))

    total_pending = len(to_dl)
    if max_dl:
        to_dl = to_dl[start : start + max_dl]
    elif start:
        to_dl = to_dl[start:]

    log(f"Pending: {total_pending}, this batch: {len(to_dl)}")

    if not to_dl:
        log("All done!")
        return

    ok = 0
    fail = 0

    for i, (doi, meta) in enumerate(to_dl):
        pdf_path = Path(meta["pdf_path"])
        title_short = (meta["title"] or "(no title)")[:80]

        log(f"\n[{i+1}/{len(to_dl)}] {doi}")
        log(f"  {title_short}")

        success = False
        for attempt in range(1, RETRY_TIMES + 1):
            if attempt > 1:
                log(f"  Retry {attempt}/{RETRY_TIMES}...")
                time.sleep(5)

            if download_pdf(doi, pdf_path):
                size = pdf_path.stat().st_size
                meta["status"] = "downloaded"
                meta["file_size_kb"] = round(size / 1024, 1)
                meta["source"] = getattr(download_pdf, "_last_source", "unknown")
                index[doi] = meta
                save_json(INDEX_FILE, index)
                ok += 1
                success = True
                break

            time.sleep(2)

        if not success:
            log(f"  FAILED")
            prev = failed.get(doi, {})
            failed[doi] = {
                "doi": doi,
                "title": meta["title"],
                "retries": prev.get("retries", 0) + RETRY_TIMES,
                "last_error": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            save_json(FAILED_FILE, failed)
            fail += 1

        if i < len(to_dl) - 1:
            time.sleep(SLEEP_BETWEEN)

        if (i + 1) % 10 == 0:
            save_json(INDEX_FILE, index)
            save_json(FAILED_FILE, failed)
            log(f"\n--- Progress: {i+1}/{len(to_dl)}, OK={ok}, FAIL={fail} ---")

    save_json(INDEX_FILE, index)
    save_json(FAILED_FILE, failed)

    total_ok = sum(1 for m in index.values() if m.get("status") == "downloaded")
    log("\n" + "=" * 60)
    log(f"DONE! Total: {len(doi_map)}, Downloaded: {total_ok}")
    log(f"  This batch: OK={ok}, FAIL={fail}")
    log(f"  Index: {INDEX_FILE}")
    log(f"  Failed list: {FAILED_FILE}")
    log(f"  PDF dir: {PDF_DIR}")
    log("=" * 60)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Batch download perovskite paper PDFs")
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--max", type=int, default=None)
    p.add_argument("--retry-failed", action="store_true")
    args = p.parse_args()
    main(start=args.start, max_dl=args.max, retry_failed=args.retry_failed)
