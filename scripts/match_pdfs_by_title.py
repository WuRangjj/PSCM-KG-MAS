import json
import re
from pathlib import Path
import PyPDF2

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

print(f"📚 元数据中有 {len(papers)} 篇文献\n")


# ========== 从PDF提取标题 ==========
def extract_title_from_pdf(pdf_path):
    """从PDF第一页提取标题"""
    try:
        with open(pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            if len(reader.pages) == 0:
                return None
            first_page = reader.pages[0]
            text = first_page.extract_text()
            if not text:
                return None
            # 取前几行作为标题候选
            lines = text.strip().split('\n')
            # 过滤掉空行和太短的行
            lines = [line.strip() for line in lines if line.strip() and len(line.strip()) > 10]
            if lines:
                # 通常第一行是标题
                return lines[0]
            return None
    except Exception as e:
        print(f"   ⚠️ 读取PDF出错: {e}")
        return None


# ========== 模糊匹配 ==========
def find_matching_paper(extracted_title):
    """用提取的标题匹配元数据中的标题"""
    if not extracted_title:
        return None

    extracted_clean = extracted_title.lower().strip()
    # 去掉末尾的句号、标点
    extracted_clean = re.sub(r'[.,;:!?]$', '', extracted_clean)

    best_match = None
    best_score = 0

    for paper in papers:
        paper_title = paper.get('TI', '').lower().strip()
        if not paper_title:
            continue

        # 方法1: 完全匹配
        if extracted_clean == paper_title:
            return paper

        # 方法2: 一个包含另一个
        if paper_title in extracted_clean or extracted_clean in paper_title:
            score = min(len(paper_title), len(extracted_clean)) / max(len(paper_title), len(extracted_clean))
            if score > best_score:
                best_score = score
                best_match = paper

        # 方法3: 标题开头匹配（前30个字符）
        if len(extracted_clean) > 20 and len(paper_title) > 20:
            if extracted_clean[:30] == paper_title[:30]:
                return paper

    # 如果相似度 > 0.6，认为匹配成功
    if best_score > 0.6:
        return best_match

    return None


# ========== 主流程 ==========
matched = 0
unmatched = []

pdf_files = list(PDF_SOURCE_DIR.glob("*.pdf"))
print(f"📄 找到 {len(pdf_files)} 个PDF文件\n")

for i, pdf_file in enumerate(pdf_files, 1):
    print(f"[{i}/{len(pdf_files)}] 处理: {pdf_file.name}")

    # 提取标题
    title = extract_title_from_pdf(pdf_file)
    if title:
        print(f"   📝 提取标题: {title[:80]}...")
        paper = find_matching_paper(title)
        if paper:
            doi = paper.get('DO', '')
            if doi:
                new_name = doi.replace('/', '_') + '.pdf'
                dest_path = PDF_DEST_DIR / new_name
                try:
                    # 复制或移动文件
                    import shutil

                    shutil.copy2(pdf_file, dest_path)
                    print(f"   ✅ 匹配成功: → {new_name}")
                    matched += 1
                except Exception as e:
                    print(f"   ❌ 复制失败: {e}")
            else:
                print(f"   ⚠️ 该文献无DOI，跳过")
        else:
            unmatched.append(pdf_file.name)
            print(f"   ❌ 无法匹配")
    else:
        unmatched.append(pdf_file.name)
        print(f"   ❌ 无法提取标题（可能是扫描版PDF）")

    print()

# ========== 统计 ==========
print("=" * 60)
print(f"📊 匹配成功: {matched} 篇")
print(f"⚠️ 未匹配: {len(unmatched)} 篇")

if unmatched:
    print("\n未匹配的文件名（需要手工处理）:")
    for name in unmatched[:20]:  # 只显示前20个
        print(f"  - {name}")
    if len(unmatched) > 20:
        print(f"  ... 还有 {len(unmatched) - 20} 个")

print(f"\n✅ 已匹配的PDF已复制到: {PDF_DEST_DIR}")