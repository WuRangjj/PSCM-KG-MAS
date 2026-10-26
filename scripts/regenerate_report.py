"""
重新生成下载报告，前 100 篇标记为已下载
"""
import re, json, time
from pathlib import Path

RIS_DIR = Path(r"C:\Users\20155\dpa4_project\data\raw\ris")
PDF_DIR = Path(r"C:\Users\20155\Desktop\钙钛矿pdf")
OA_CACHE = Path(r"C:\Users\20155\dpa4_project\data\oa_status.json")
INDEX_FILE = Path(r"C:\Users\20155\dpa4_project\data\pdf_index.json")
REPORT = Path(r"C:\Users\20155\dpa4_project\data\download_report.html")

def main():
    # Load OA cache
    with open(OA_CACHE, "r", encoding="utf-8") as f:
        oa_cache = json.load(f)

    # Parse RIS files in order
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

            papers.append({
                "doi": doi,
                "title": ti.group(1).strip() if ti else "",
                "authors": ", ".join(au[:3]),
                "year": py.group(1) if py else "",
                "journal": t2.group(1).strip() if t2 else "",
                "cited": int(nc.group(1)) if nc else 0,
                "is_oa": oa.get("is_oa", False),
                "oa_urls": oa.get("pdf_urls", []),
            })

    # Mark first 100 as downloaded
    for i, p in enumerate(papers):
        p["downloaded"] = i < 100

    total = len(papers)
    downloaded_count = sum(1 for p in papers if p["downloaded"])
    oa_count = sum(1 for p in papers if p["is_oa"])

    # Save mapping index
    index = {}
    for p in papers:
        if p["downloaded"]:
            index[p["doi"]] = {
                "doi": p["doi"],
                "title": p["title"],
                "year": p["year"],
                "journal": p["journal"],
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
.stat{{text-align:center}}.stat .num{{font-size:32px;font-weight:bold}}.stat .label{{color:#666;font-size:13px}}
.stat.green .num{{color:#27ae60}}.stat.blue .num{{color:#4a90d9}}.stat.red .num{{color:#e74c3c}}
.tips{{background:#fffbe6;border-left:4px solid #f39c12;padding:12px 16px;margin:15px 0;border-radius:4px}}
table{{width:100%;border-collapse:collapse;background:#fff;box-shadow:0 2px 5px rgba(0,0,0,.08);font-size:13px;margin:10px 0}}
th{{background:#4a90d9;color:#fff;padding:10px 8px;text-align:left;position:sticky;top:0;z-index:10}}
td{{padding:7px 8px;border-bottom:1px solid #eee}}tr:hover{{background:#f0f7ff}}
tr.oa{{background:#f6fff6}}tr.oa:hover{{background:#e8fae8}}tr.done{{background:#e8f0fe}}
a{{color:#4a90d9;text-decoration:none;margin:0 3px;white-space:nowrap}}a:hover{{text-decoration:underline}}
.badge{{padding:2px 7px;border-radius:10px;font-size:10px;font-weight:bold}}
.badge-oa{{background:#d4edda;color:#155724}}.badge-closed{{background:#f8d7da;color:#721c24}}.badge-done{{background:#cce5ff;color:#004085}}
.btn{{display:inline-block;padding:10px 20px;background:#4a90d9;color:#fff!important;border-radius:6px;margin:10px 5px;font-weight:bold}}
.btn:hover{{background:#357abd}}
.tab-btn{{padding:8px 16px;border:2px solid #4a90d9;background:#fff;color:#4a90d9;cursor:pointer;border-radius:6px;margin:2px;font-size:13px}}
.tab-btn.active{{background:#4a90d9;color:#fff}}
.filter{{margin:10px 0}}.filter input{{padding:8px;border:1px solid #ddd;border-radius:4px;width:300px;font-size:14px}}
</style>
</head>
<body>

<h1>钙钛矿文献 PDF 下载报告</h1>
<p>生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<div class="stats">
<div class="stat green"><div class="num">{total}</div><div class="label">总文献数</div></div>
<div class="stat blue"><div class="num">{oa_count}</div><div class="label">Open Access ({oa_count*100//total}%)</div></div>
<div class="stat green"><div class="num">{downloaded_count}</div><div class="label">已下载</div></div>
<div class="stat red"><div class="num">{len(undownloaded)}</div><div class="label">待下载 (#101-{total})</div></div>
</div>

<div class="tips">
<b>手动下载 Sci-Hub：</b> 点击 SciHub 链接 → 等 altcha 解密 → PDF 出现后 Ctrl+S 保存<br>
<b>命名规则：</b> 按顺序编号 #{101}-{total}，保存时文件名用 <b>DOI</b>（斜杠换下划线）
</div>

<div style="margin:10px 0">
<button class="tab-btn active" onclick="showTab('pending')">待下载 (#101-{total})</button>
<button class="tab-btn" onclick="showTab('done')">已下载 (#1-100)</button>
</div>

<div class="filter">
<input type="text" id="search" placeholder="搜索标题、期刊..." oninput="filterTable()">
<select id="oaFilter" onchange="filterTable()" style="padding:8px;margin-left:10px;border:1px solid #ddd;border-radius:4px">
<option value="all">全部</option><option value="oa">仅 OA</option><option value="closed">仅付费</option>
</select>
<a href="batch_downloader.html" style="margin-left:20px;font-weight:bold;color:#e74c3c">批量打开器（Sci-Hub）</a>
</div>

<!-- Pending table -->
<table id="pendingTable">
<thead><tr><th>#</th><th>标题</th><th>期刊</th><th>年份</th><th>被引</th><th>OA</th><th>链接</th></tr></thead>
<tbody>
"""
    for i, p in enumerate(undownloaded):
        row_class = ' class="oa"' if p["is_oa"] else ""
        oa_badge = '<span class="badge badge-oa">OA</span>' if p["is_oa"] else '<span class="badge badge-closed">付费</span>'
        idx = i + 101  # Starts from 101
        links = f'<a href="https://sci-hub.st/{p["doi"]}" target="_blank">SciHub</a>'
        links += f' <a href="https://doi.org/{p["doi"]}" target="_blank">DOI</a>'
        for j, u in enumerate(p["oa_urls"][:1]):
            links += f' <a href="{u}" target="_blank">OA</a>'

        t = p["title"].replace("<","&lt;").replace(">","&gt;").replace("&","&amp;")
        j = p["journal"].replace("<","&lt;").replace(">","&gt;").replace("&","&amp;")

        html += f'<tr{row_class}><td>{idx}</td><td style="max-width:440px">{t[:130]}</td><td>{j[:35]}</td><td>{p["year"]}</td><td>{p["cited"]}</td><td>{oa_badge}</td><td style="white-space:nowrap">{links}</td></tr>\n'

    html += """</tbody></table>

<!-- Done table (hidden by default) -->
<table id="doneTable" style="display:none">
<thead><tr><th>#</th><th>标题</th><th>期刊</th><th>年份</th><th>被引</th><th>OA</th><th>DOI</th></tr></thead>
<tbody>
"""
    for i, p in enumerate(papers[:100]):
        oa_badge = '<span class="badge badge-oa">OA</span>' if p["is_oa"] else '<span class="badge badge-closed">付费</span>'
        t = p["title"].replace("<","&lt;").replace(">","&gt;").replace("&","&amp;")
        j = p["journal"].replace("<","&lt;").replace(">","&gt;").replace("&","&amp;")
        html += f'<tr class="done"><td>{i+1}</td><td style="max-width:440px">{t[:130]}</td><td>{j[:35]}</td><td>{p["year"]}</td><td>{p["cited"]}</td><td>{oa_badge}</td><td style="font-size:11px">{p["doi"]}</td></tr>\n'

    html += """
</tbody></table>

<script>
function showTab(tab) {
    document.getElementById('pendingTable').style.display = tab === 'pending' ? '' : 'none';
    document.getElementById('doneTable').style.display = tab === 'done' ? '' : 'none';
    var btns = document.querySelectorAll('.tab-btn');
    btns[0].classList.toggle('active', tab === 'pending');
    btns[1].classList.toggle('active', tab === 'done');
}

function filterTable() {
    var search = document.getElementById('search').value.toLowerCase();
    var oa = document.getElementById('oaFilter').value;
    var rows = document.querySelectorAll('#pendingTable tbody tr');
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
    print(f"  Total: {total}")
    print(f"  Downloaded: #1-100 (100 papers)")
    print(f"  Pending: #{101}-{total} ({len(undownloaded)} papers)")
    print(f"Index saved: {INDEX_FILE}")

if __name__ == "__main__":
    main()
