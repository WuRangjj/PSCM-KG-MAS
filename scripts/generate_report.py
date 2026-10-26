"""
生成下载报告 HTML + DOI 索引
"""
import re, json, time
from pathlib import Path

RIS_DIR = Path(r"C:\Users\20155\dpa4_project\data\raw\ris")
PDF_DIR = Path(r"C:\Users\20155\dpa4_project\data\pdf")
OA_CACHE = Path(r"C:\Users\20155\dpa4_project\data\oa_status.json")
INDEX_FILE = Path(r"C:\Users\20155\dpa4_project\data\pdf_index.json")
REPORT = Path(r"C:\Users\20155\dpa4_project\data\download_report.html")

def main():
    # Load OA cache
    with open(OA_CACHE, "r", encoding="utf-8") as f:
        oa_cache = json.load(f)

    # Parse RIS
    ris_files = sorted(RIS_DIR.glob("csp_*.ris"))
    papers = []
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
            au = [a.strip() for a in re.findall(r"AU  - (.+)", record)]
            nc = re.search(r"Times Cited[^\d]*(\d+)", record)

            oa = oa_cache.get(doi, {})
            pdf_fn = doi.replace("/", "_") + ".pdf"
            pdf_path = PDF_DIR / pdf_fn

            downloaded = pdf_path.exists() and pdf_path.stat().st_size > 3000
            if downloaded:
                with open(pdf_path, "rb") as f:
                    downloaded = b"%PDF-" in f.read(2048)

            papers.append({
                "doi": doi,
                "title": ti.group(1).strip() if ti else "",
                "authors": ", ".join(au[:3]),
                "year": py.group(1) if py else "",
                "journal": t2.group(1).strip() if t2 else "",
                "cited": int(nc.group(1)) if nc else 0,
                "is_oa": oa.get("is_oa", False),
                "oa_urls": oa.get("pdf_urls", []),
                "downloaded": downloaded,
                "pdf_size": round(pdf_path.stat().st_size/1024, 1) if downloaded else 0,
                "doi_url": f"https://doi.org/{doi}",
                "scihub": f"https://sci-hub.st/{doi}",
                # WebVPN proxy URLs
                "proxy_doi": f"https://doi-org-s.webvpn.wzu.edu.cn/{doi}",
                "proxy_scihub": f"https://sci-hub-st-s.webvpn.wzu.edu.cn/{doi}",
            })

    downloaded_count = sum(1 for p in papers if p["downloaded"])
    oa_count = sum(1 for p in papers if p["is_oa"])

    # Save index
    index = {}
    for p in papers:
        if p["downloaded"]:
            index[p["doi"]] = {
                "doi": p["doi"],
                "title": p["title"],
                "authors": p["authors"],
                "year": p["year"],
                "journal": p["journal"],
                "pdf_filename": p["doi"].replace("/", "_") + ".pdf",
                "pdf_path": str(PDF_DIR / (p["doi"].replace("/", "_") + ".pdf")),
                "file_size_kb": p["pdf_size"],
                "status": "downloaded",
                "is_oa": p["is_oa"],
            }
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    # Filter undownloaded
    undownloaded = [p for p in papers if not p["downloaded"]]

    # Generate HTML
    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>钙钛矿文献 PDF 下载报告</title>
<style>
body{{font-family:'Segoe UI',Arial,sans-serif;max-width:1200px;margin:20px auto;padding:20px;background:#f5f5f5}}
h1{{color:#333}}h2{{color:#555;margin-top:30px}}
.stats{{background:#fff;padding:20px;border-radius:10px;margin:15px 0;box-shadow:0 2px 5px rgba(0,0,0,.08);display:flex;gap:30px;flex-wrap:wrap}}
.stat{{text-align:center}}
.stat .num{{font-size:32px;font-weight:bold}}
.stat .label{{color:#666;font-size:13px}}
.stat.green .num{{color:#27ae60}}
.stat.blue .num{{color:#4a90d9}}
.stat.red .num{{color:#e74c3c}}
.tips{{background:#fffbe6;border-left:4px solid #f39c12;padding:12px 16px;margin:15px 0;border-radius:4px}}
table{{width:100%;border-collapse:collapse;background:#fff;box-shadow:0 2px 5px rgba(0,0,0,.08);font-size:13px;margin:10px 0}}
th{{background:#4a90d9;color:#fff;padding:10px 8px;text-align:left;position:sticky;top:0;z-index:10}}
td{{padding:7px 8px;border-bottom:1px solid #eee}}
tr:hover{{background:#f0f7ff}}
tr.oa{{background:#f6fff6}}tr.oa:hover{{background:#e8fae8}}
a{{color:#4a90d9;text-decoration:none;margin:0 3px;white-space:nowrap}}a:hover{{text-decoration:underline}}
.badge{{padding:2px 7px;border-radius:10px;font-size:10px;font-weight:bold}}
.badge-oa{{background:#d4edda;color:#155724}}.badge-closed{{background:#f8d7da;color:#721c24}}
.badge-dl{{background:#cce5ff;color:#004085}}
.btn{{display:inline-block;padding:10px 20px;background:#4a90d9;color:#fff!important;border-radius:6px;margin:10px 5px;font-weight:bold}}
.btn:hover{{background:#357abd}}
.filter{{margin:10px 0}} .filter input{{padding:8px;border:1px solid #ddd;border-radius:4px;width:300px;font-size:14px}}
</style>
</head>
<body>

<h1>🔬 钙钛矿文献 PDF 下载报告</h1>
<p>生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<div class="stats">
<div class="stat green"><div class="num">{len(papers)}</div><div class="label">总文献数</div></div>
<div class="stat blue"><div class="num">{oa_count}</div><div class="label">Open Access ({oa_count*100//len(papers)}%)</div></div>
<div class="stat green"><div class="num">{downloaded_count}</div><div class="label">✅ 已下载</div></div>
<div class="stat red"><div class="num">{len(undownloaded)}</div><div class="label">❌ 待下载</div></div>
</div>

<div class="tips">
<b>💡 使用说明：</b><br>
1. 确保你已在浏览器中<b>登录 WZU WebVPN</b><br>
2. 点击 <b style="color:#27ae60">Proxy</b> 链接通过学校代理访问（推荐）<br>
3. 点击 <b style="color:#4a90d9">DOI</b> 链接直接访问出版社页面<br>
4. 点击 <b style="color:#e74c3c">SciHub</b> 链接尝试免费下载<br>
5. 推荐使用 <b>DownThemAll</b> 或 <b>Simple Mass Downloader</b> 浏览器扩展批量下载
</div>

<div class="filter">
🔍 搜索: <input type="text" id="search" placeholder="输入标题、期刊、年份..." oninput="filterTable()">
<select id="oaFilter" onchange="filterTable()" style="padding:8px;margin-left:10px;border:1px solid #ddd;border-radius:4px">
<option value="all">全部</option><option value="oa">仅 OA</option><option value="closed">仅付费</option>
</select>
</div>

<table id="paperTable">
<thead><tr>
<th>#</th><th>标题</th><th>期刊</th><th>年份</th><th>引用</th><th>OA</th><th>下载链接</th>
</tr></thead>
<tbody>
"""
    for i, p in enumerate(undownloaded, 1):
        row_class = ' class="oa"' if p["is_oa"] else ""
        oa_badge = '<span class="badge badge-oa">OA</span>' if p["is_oa"] else '<span class="badge badge-closed">付费</span>'
        links = ""
        links += f'<a href="{p["doi_url"]}" target="_blank">📄 DOI</a>'
        links += f'<a href="{p["proxy_doi"]}" target="_blank" style="color:#27ae60">🔗 代理</a>'
        links += f'<a href="{p["scihub"]}" target="_blank" style="color:#e74c3c">🏴‍☠️ SciHub</a>'
        for j, u in enumerate(p["oa_urls"][:1]):
            links += f' <a href="{u}" target="_blank" style="color:#f39c12">📥 OA</a>'

        title_escaped = p["title"].replace("<", "&lt;").replace(">", "&gt;").replace("&", "&amp;")
        journal_escaped = p["journal"].replace("<", "&lt;").replace(">", "&gt;").replace("&", "&amp;")

        html += f"""<tr{row_class}>
<td>{i}</td>
<td style="max-width:440px">{title_escaped[:130]}</td>
<td>{journal_escaped[:35]}</td>
<td>{p["year"]}</td>
<td>{p["cited"]}</td>
<td>{oa_badge}</td>
<td style="white-space:nowrap">{links}</td>
</tr>
"""

    html += f"""
</tbody>
</table>

<div style="margin-top:20px">
<p>已下载 {downloaded_count} 篇，剩余 {len(undownloaded)} 篇</p>
<h3>✅ 已下载列表</h3>
<table>
<thead><tr><th>DOI</th><th>标题</th><th>大小(KB)</th></tr></thead>
<tbody>
"""
    for p in papers:
        if p["downloaded"]:
            t = p["title"].replace("<","&lt;").replace(">","&gt;").replace("&","&amp;")
            html += f'<tr><td>{p["doi"]}</td><td>{t[:100]}</td><td>{p["pdf_size"]}</td></tr>\n'

    html += """
</tbody>
</table>
</div>

<script>
function filterTable() {
    var search = document.getElementById('search').value.toLowerCase();
    var oa = document.getElementById('oaFilter').value;
    var rows = document.querySelectorAll('#paperTable tbody tr');
    rows.forEach(function(row) {
        var text = row.textContent.toLowerCase();
        var isOa = row.classList.contains('oa');
        var show = text.includes(search);
        if (oa === 'oa' && !isOa) show = false;
        if (oa === 'closed' && isOa) show = false;
        row.style.display = show ? '' : 'none';
    });
}
</script>

</body></html>"""

    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Report saved: {REPORT}")
    print(f"  Total: {len(papers)} papers")
    print(f"  OA: {oa_count}")
    print(f"  Downloaded: {downloaded_count}")
    print(f"  Remaining: {len(undownloaded)} (open HTML in browser)")
    print(f"Index saved: {INDEX_FILE}")

if __name__ == "__main__":
    main()
