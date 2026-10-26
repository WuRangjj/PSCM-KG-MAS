import json
import re
import shutil
from pathlib import Path

# ========== 配置 ==========
PDF_SOURCE_DIR = Path(r"C:\Users\20155\Desktop\pdfs")  # 桌面上的PDF文件夹
PDF_DEST_DIR = Path(r"C:\Users\20155\dpa4_project\data\pdfs")
META_PATH = Path(r"C:\Users\20155\dpa4_project\data\parsed\filtered_papers.json")

PDF_DEST_DIR.mkdir(parents=True, exist_ok=True)

# ========== 读取元数据 ==========
with open(META_PATH, 'r', encoding='utf-8') as f:
    data = json.load(f)

papers = data.get('kept_papers', [])

print(f"📚 元数据中有 {len(papers)} 篇文献\n")

# ========== 构建索引 ==========
# 1. DOI 索引
doi_index = {}
for paper in papers:
    doi = paper.get('DO', '')
    if doi:
        # 同时存原始格式和替换后的格式
        doi_index[doi] = paper
        doi_index[doi.replace('/', '_')] = paper
        doi_index[doi.replace('/', '@')] = paper

# 2. 作者+年份索引
author_year_index = {}
for paper in papers:
    authors = paper.get('AU', [])
    year = paper.get('PY', '')
    if authors and year:
        # 取第一作者
        first_author = authors[0].lower().strip()
        # 提取姓氏（去掉名字缩写）
        last_name = first_author.split()[-1] if first_author else ''
        if last_name:
            key = f"{last_name}{year}".lower()
            author_year_index[key] = paper
            # 也存带连字符的版本
            author_year_index[f"{last_name}-{year}".lower()] = paper

print(f"📊 构建索引: DOI索引 {len(doi_index)} 条, 作者年份索引 {len(author_year_index)} 条\n")

# ========== 匹配 ==========
matched = 0
unmatched = []

for pdf_file in PDF_SOURCE_DIR.glob("*.pdf"):
    filename = pdf_file.stem  # 去掉 .pdf

    # 方法1: 直接用文件名匹配 DOI 索引
    if filename in doi_index:
        paper = doi_index[filename]
        doi = paper.get('DO', '')
        new_name = doi.replace('/', '_') + '.pdf'
        shutil.copy2(pdf_file, PDF_DEST_DIR / new_name)
        print(f"✅ {pdf_file.name} → {new_name} (DOI匹配)")
        matched += 1
        continue

    # 方法2: 尝试从文件名中提取 DOI 片段
    # 比如 "10.1002@anie.201601757" → 提取 "10.1002/anie.201601757"
    doi_match = re.search(r'(10\.\d+)[@_](.+)', filename)
    if doi_match:
        doi_candidate = f"{doi_match.group(1)}/{doi_match.group(2)}"
        if doi_candidate in doi_index:
            paper = doi_index[doi_candidate]
            new_name = doi_candidate.replace('/', '_') + '.pdf'
            shutil.copy2(pdf_file, PDF_DEST_DIR / new_name)
            print(f"✅ {pdf_file.name} → {new_name} (从文件名提取DOI)")
            matched += 1
            continue

    # 方法3: 作者+年份匹配
    # 文件名如 "abdi-jalebi2018" → 提取 "abdi2018"
    # 去掉中间的连字符
    cleaned = filename.replace('-', '').replace('_', '').lower()
    # 尝试匹配 作者名+年份
    for key, paper in author_year_index.items():
        if key in cleaned or cleaned in key:
            doi = paper.get('DO', '')
            if doi:
                new_name = doi.replace('/', '_') + '.pdf'
                shutil.copy2(pdf_file, PDF_DEST_DIR / new_name)
                print(f"✅ {pdf_file.name} → {new_name} (作者年份匹配: {key})")
                matched += 1
                break
        # 也尝试部分匹配：文件名包含作者名且包含年份
        author_part = key[:-4] if len(key) > 4 else ''
        year_part = key[-4:] if len(key) > 4 else ''
        if author_part and year_part and author_part in cleaned and year_part in cleaned:
            doi = paper.get('DO', '')
            if doi:
                new_name = doi.replace('/', '_') + '.pdf'
                shutil.copy2(pdf_file, PDF_DEST_DIR / new_name)
                print(f"✅ {pdf_file.name} → {new_name} (作者年份片段匹配)")
                matched += 1
                break
    else:
        unmatched.append(pdf_file.name)
        print(f"❌ 未匹配: {pdf_file.name}")

# ========== 统计 ==========
print("\n" + "=" * 60)
print(f"📊 本次匹配成功: {matched} 篇")
print(f"⚠️ 本次未匹配: {len(unmatched)} 篇")

if unmatched:
    print("\n仍未匹配的文件名（需要手工处理）:")
    for name in unmatched[:30]:
        print(f"  - {name}")
    if len(unmatched) > 30:
        print(f"  ... 还有 {len(unmatched) - 30} 个")

print(f"\n✅ 总匹配数: {matched} 篇")
print(f"📁 PDF已复制到: {PDF_DEST_DIR}")