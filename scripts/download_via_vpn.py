"""
通过学校 WebVPN 批量下载论文 PDF
使用从浏览器导出的 cookie 进行认证
"""

import re, json, time, os, subprocess, sys
from pathlib import Path
from urllib.parse import urljoin

# ===== 配置 =====
COOKIE_STRING = 'SERVERID=Server1; SID="USW2EC0BEBSsRruG8zhuWYdF5gwTD"; _webvpn_key=eyJhbGciOiJIUzI1NiJ9.eyJ1c2VyIjoiMjU0NTA5MzYwMjIiLCJncm91cHMiOlsyM10sImlhdCI6MTc4NDUyNjIwMywiZXhwIjoxNzg0NjEyNjAzfQ.1AK3g5yG8XgdO5jRdAABqzqDqXG9OVDgdYkxb4pQHkY; webvpn_username=25450936022%7C1784526203%7C6944cf948ee655b8c928e5de5598aa0531792d02; _astraeus_session=bW1uZFlzZ0FjM3pNOG9wMkFRVERIY3NHM3dtVVliTmJ6czkwd0NlMUk2ZFl4Z0lTODFDRDdaazJ2VlExQTlrQ2lKR2lVZ3pZY01UenZSdnUrMi9xeVVJSVNBOXlaNU9MbWFpbis5ckt6b0NkVHk3NDA4L3BpOThWb0lSSCtrUENIenFVWk4xUHY0NkwzRWdkUjQ3THN6MndHc2lMZHFoUXhlQit1Tm0yM0VxV0t1emZMUzl1WjBneFY4bXpUMGRtMHE2M3BjUHF2bmVOcjZkMzQ4NlN6elRjSm5qVEtOR0I5Y3laanFtbVAwWTd4akNBdnZSSERTOVZSZUdJMFRsY2VDS01TZG5ISGVlZXFmQ0wvQ0xJMkJzYUdCRHgrdHBwbVQ2RllUUFlkYXkrelpLRWJ0dFpsRzZiWUNOdTVSaW85R2xSQUpjNnFJRTNDYjRWTndxNG9nPT0tLXQ2WDZHYkxrdHRJMEtJaCs3QVJlZ3c9PQ%3D%3D--da0e6b93763f2b5360a347c04bc4cf08ad99c467'

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 Edg/127.0.0.0"

# Publisher → WebVPN proxy mapping
# DOI prefix → (publisher_domain, vpn_domain)
PUBLISHER_MAP = {
    "10.1126": ("www.science.org", "science-org-s.webvpn.wzu.edu.cn"),
    "10.1038": ("www.nature.com", "nature-com-s.webvpn.wzu.edu.cn"),
    "10.1021": ("pubs.acs.org", "pubs-acs-org-s.webvpn.wzu.edu.cn"),
    "10.1039": ("pubs.rsc.org", "pubs-rsc-org-s.webvpn.wzu.edu.cn"),
    "10.1002": ("onlinelibrary.wiley.com", "onlinelibrary-wiley-com-s.webvpn.wzu.edu.cn"),
    "10.1016": ("www.sciencedirect.com", "sciencedirect-com-s.webvpn.wzu.edu.cn"),
    "10.1007": ("link.springer.com", "link-springer-com-s.webvpn.wzu.edu.cn"),
    "10.1103": ("journals.aps.org", "journals-aps-org-s.webvpn.wzu.edu.cn"),
    "10.1063": ("pubs.aip.org", "pubs-aip-org-s.webvpn.wzu.edu.cn"),
    "10.1088": ("iopscience.iop.org", "iopscience-iop-org-s.webvpn.wzu.edu.cn"),
    "10.1002/adma": ("onlinelibrary.wiley.com", "onlinelibrary-wiley-com-s.webvpn.wzu.edu.cn"),
    "10.1002/aenm": ("onlinelibrary.wiley.com", "onlinelibrary-wiley-com-s.webvpn.wzu.edu.cn"),
    "10.1002/anie": ("onlinelibrary.wiley.com", "onlinelibrary-wiley-com-s.webvpn.wzu.edu.cn"),
}

PDF_DIR = Path(r"C:\Users\20155\Desktop\钙钛矿pdf")
OA_CACHE = Path(r"C:\Users\20155\dpa4_project\data\oa_status.json")
INDEX_FILE = Path(r"C:\Users\20155\dpa4_project\data\pdf_index.json")
LOG_FILE = Path(r"C:\Users\20155\Desktop\钙钛矿pdf\download_log.txt")

PDF_DIR.mkdir(parents=True, exist_ok=True)

def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    try: print(line)
    except: print(line.encode('ascii', errors='replace').decode('ascii'))
    with open(LOG_FILE, "a", encoding="utf-8") as f: f.write(line + "\n")

def curl_get(url, timeout=30):
    """curl GET → bytes or None"""
    r = subprocess.run(
        ["curl", "-s", "-L", "--connect-timeout", "12", "--max-time", str(timeout),
         "-H", f"User-Agent: {UA}", "-b", COOKIE_STRING, url],
        capture_output=True, timeout=timeout+10,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if r.returncode == 0 and r.stdout: return r.stdout
    return None

def curl_download(url, outpath, timeout=90):
    """Download via curl → (ok, size)"""
    r = subprocess.run(
        ["curl", "-s", "-L", "--connect-timeout", "12", "--max-time", str(timeout),
         "-H", f"User-Agent: {UA}", "-b", COOKIE_STRING, "-o", outpath, url],
        capture_output=True, timeout=timeout+10,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if r.returncode == 0 and os.path.exists(outpath):
        size = os.path.getsize(outpath)
        if size > 5000:
            with open(outpath, "rb") as f:
                if b"%PDF-" in f.read(4096):
                    return (True, size)
        if size < 8000: os.unlink(outpath)  # clean junk
    return (False, 0)

def get_vpn_url(doi):
    """Convert DOI to WebVPN proxy URL."""
    for prefix, (pub_domain, vpn_domain) in PUBLISHER_MAP.items():
        if doi.startswith(prefix):
            return f"https://{vpn_domain}/doi/{doi}"
    # Fallback: try to guess
    return None

def get_pdf_url_from_page(html_bytes, vpn_domain):
    """Parse publisher page for PDF download URL."""
    try:
        text = html_bytes.decode('utf-8', errors='replace')
    except:
        return None

    pdf_url = None

    # Pattern 1: citation_pdf_url meta
    m = re.search(r'<meta\s+name="citation_pdf_url"\s+content="([^"]+)"', text, re.I)
    if m:
        pdf_url = m.group(1)
        if pdf_url.startswith("/"):
            pdf_url = f"https://{vpn_domain}{pdf_url}"
        return pdf_url

    # Pattern 2: PDF link in href
    for m in re.finditer(r'href\s*=\s*["\']([^"\']*?\.pdf[^"\'\s]*)["\']', text, re.I):
        u = m.group(1)
        if 'citation' in u.lower() or 'download' in u.lower() or '/pdf/' in u.lower():
            pdf_url = u
            break
    if not pdf_url:
        for m in re.finditer(r'href\s*=\s*["\']([^"\']*?/pdf/[^"\'\s]*)["\']', text, re.I):
            pdf_url = m.group(1); break

    if pdf_url:
        if pdf_url.startswith("//"): pdf_url = "https:" + pdf_url
        elif pdf_url.startswith("/"): pdf_url = f"https://{vpn_domain}{pdf_url}"
        elif not pdf_url.startswith("http"): pdf_url = f"https://{vpn_domain}/{pdf_url}"
        return pdf_url

    # Pattern 3: Science-specific PDF pattern
    m = re.search(r'["\'](/doi/pdf/\d+\.\d+/[^"\']+)["\']', text)
    if m:
        return f"https://{vpn_domain}{m.group(1)}"

    return None

def download_one(doi, pdf_filename=None):
    """Download single paper. Returns (success, size_kb)."""
    if pdf_filename is None:
        pdf_filename = doi.replace("/", "_") + ".pdf"
    pdf_path = PDF_DIR / pdf_filename

    # Already downloaded?
    if pdf_path.exists() and pdf_path.stat().st_size > 5000:
        with open(pdf_path, "rb") as f:
            if b"%PDF-" in f.read(4096):
                return (True, round(pdf_path.stat().st_size/1024, 1))

    # Get VPN URL
    vpn_url = get_vpn_url(doi)
    if not vpn_url:
        log(f"  No VPN mapping for {doi}")
        return (False, 0)

    # Get publisher page
    log(f"  Fetching: {vpn_url[:80]}...")
    html = curl_get(vpn_url, timeout=25)
    if not html:
        log(f"  Failed to fetch page")
        return (False, 0)

    vpn_domain = vpn_url.split("/")[2]

    # Find PDF URL
    pdf_url = get_pdf_url_from_page(html, vpn_domain)

    if not pdf_url:
        # Try common patterns based on publisher
        if "science-org" in vpn_domain:
            pdf_url = f"https://{vpn_domain}/doi/pdf/{doi}?download=true"
        elif "nature-com" in vpn_domain:
            # Nature: replace /articles/xxx with /articles/xxx.pdf
            article_id = doi.split("/")[-1] if "/" in doi else doi
            pdf_url = f"https://{vpn_domain}/articles/{article_id}.pdf"
        elif "pubs-acs" in vpn_domain:
            pdf_url = f"https://{vpn_domain}/doi/pdf/{doi}?download=true"
        elif "pubs-rsc" in vpn_domain:
            pdf_url = f"https://{vpn_domain}/en/content/articlepdf/2025/ee/{doi.split('/')[-1]}"
        elif "wiley" in vpn_domain:
            pdf_url = f"https://{vpn_domain}/doi/pdfdirect/{doi}?download=true"

    if pdf_url:
        log(f"  PDF URL: {pdf_url[:100]}...")
        ok, size = curl_download(pdf_url, str(pdf_path), timeout=90)
        if ok:
            return (True, round(size/1024, 1))
        else:
            log(f"  Download failed from PDF URL")
    else:
        log(f"  No PDF URL found on page")

    return (False, 0)

def main():
    log("=" * 50)
    log("Perovskite PDF Download via WebVPN")
    log("=" * 50)

    # Load OA cache for DOI list
    with open(OA_CACHE, "r", encoding="utf-8") as f:
        oa_cache = json.load(f)

    dois = list(oa_cache.keys())
    log(f"Total: {len(dois)} papers")

    # Count existing
    existing = 0
    for doi in dois:
        fn = doi.replace("/", "_") + ".pdf"
        p = PDF_DIR / fn
        if p.exists() and p.stat().st_size > 5000:
            with open(p, "rb") as f:
                if b"%PDF-" in f.read(4096): existing += 1
    log(f"Already downloaded: {existing}")

    pending = [d for d in dois if not (
        (PDF_DIR / (d.replace("/", "_") + ".pdf")).exists() and
        (PDF_DIR / (d.replace("/", "_") + ".pdf")).stat().st_size > 5000
    )]
    log(f"Pending: {len(pending)}")

    ok, fail = 0, 0
    for i, doi in enumerate(pending):
        log(f"\n[{i+1}/{len(pending)}] {doi}")
        success, size = download_one(doi)
        if success:
            log(f"  OK! ({size} KB)")
            ok += 1
        else:
            log(f"  FAILED")
            fail += 1

        if (i+1) % 10 == 0:
            log(f"\n--- Progress: {i+1}/{len(pending)} OK={ok} FAIL={fail} ---")

        if i < len(pending) - 1:
            time.sleep(2)  # Be nice

    log(f"\n{'='*50}")
    log(f"DONE! OK={ok} FAIL={fail}")
    log(f"Files in: {PDF_DIR}")

if __name__ == "__main__":
    main()
