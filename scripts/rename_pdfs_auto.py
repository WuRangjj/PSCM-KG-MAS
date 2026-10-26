import json
import os
import re
from pathlib import Path

# ========== 配置 ==========
PDF_SOURCE_DIR = Path(r"C:\Users\20155\Desktop\pdfs")  # 你桌面上的PDF文件夹
PDF_DEST_DIR = Path(r"C:\Users\20155\dpa4_project\data\pdfs")
META_PATH = Path(r"C:\Users\20155\dpa4_project\data\parsed\filtered_papers.json")

# 创建目标目录
PDF_DEST_DIR.mkdir(parents=True, exist_ok=True)

# ========== 读取元数据 ==========
with open(META_PATH, 'r', encoding='utf-8') as f:
    data = json.load(f)

papers = data.get('kept_papers', [])

# 构建 DOI → 标题 映射
doi_to_title = {}
for paper in papers:
    doi = paper.get('DO', '')
    if doi:
        doi_to_title[doi] = paper.get('TI', '')

print(f"📚 元数据中有 {len(doi_to_title)} 篇文献")

# ========== 匹配和重命名 ==========
matched = 0
unmatched = []

# 遍历桌面上的PDF
for pdf_file in PDF_SOURCE_DIR.glob("*.pdf"):
    # 尝试从文件名中提取DOI（支持多种格式）
    content = pdf_file.stem  # 去掉 .pdf

    # 尝试1：文件名本身就是DOI格式（10.1126_science.aaa9272）
    doi_candidate = content.replace('_', '/')
    if doi_candidate in doi_to_title:
        new_name = f"{doi_candidate.replace('/', '_')}.pdf"
        dest_path = PDF_DEST_DIR / new_name
        os.rename(pdf_file, dest_path)
        print(f"✅ 匹配成功: {pdf_file.name} → {new_name}")
        matched += 1
        continue

    # 尝试2：从文件名中用正则提取DOI（如 1-s2.0-S0038092X24001326-main）
    doi_match = re.search(r'(10\.\d+/\S+)', content.replace('_', '/'))
    if doi_match:
        doi_candidate = doi_match.group(1)
        if doi_candidate in doi_to_title:
            new_name = f"{doi_candidate.replace('/', '_')}.pdf"
            dest_path = PDF_DEST_DIR / new_name
            os.rename(pdf_file, dest_path)
            print(f"✅ 匹配成功: {pdf_file.name} → {new_name}")
            matched += 1
            continue

    # 尝试3：从PDF文件内部读取DOI（需要PyPDF2）
    try:
        import PyPDF2

        with open(pdf_file, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            first_page = reader.pages[0]
            text = first_page.extract_text()
            doi_match = re.search(r'(10\.\d+/\S+)', text)
            if doi_match:
                doi_candidate = doi_match.group(1)
                if doi_candidate in doi_to_title:
                    new_name = f"{doi_candidate.replace('/', '_')}.pdf"
                    dest_path = PDF_DEST_DIR / new_name
                    os.rename(pdf_file, dest_path)
                    print(f"✅ 匹配成功（从PDF内容提取）: {pdf_file.name} → {new_name}")
                    matched += 1
                    continue
    except:
        pass

    # 都没匹配上
    unmatched.append(pdf_file.name)

print(f"\n📊 总计匹配成功: {matched} 篇")
print(f"⚠️ 未匹配: {len(unmatched)} 篇")
if unmatched:
    print("未匹配的文件名:")
    for name in unmatched:
        print(f"  - {name}")