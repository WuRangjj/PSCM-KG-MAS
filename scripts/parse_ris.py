import os
import re
import json
from pathlib import Path

# 配置路径
LITERATURE_DIR = Path(r"C:\Users\20155\dpa4_project\data\raw\ris")
OUTPUT_DIR = Path(r"C:\Users\20155\dpa4_project\data\parsed")

# 创建输出目录
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def parse_ris_file(file_path):
    """
    解析单个 RIS 文件，提取每篇文献的：
    - TI: 标题
    - AU: 作者列表
    - AB: 摘要（核心！用于语义筛选）
    - KW: 关键词
    - PY: 出版年份
    - DO: DOI
    - SN: ISSN
    - VL/IS: 卷/期
    - SP/EP: 页码
    - CR_COUNT: 参考文献数量
    - TIMES_CITED: 被引次数
    - T2: 期刊名
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 按记录分割（每条记录以 "TY  - " 开头）
    records = re.split(r'(?=TY  - )', content)
    parsed_records = []

    for record in records:
        if not record.strip():
            continue

        # 提取各字段
        fields = {
            'TI': '',  # 标题
            'AU': [],  # 作者列表
            'AB': '',  # 摘要
            'KW': [],  # 关键词
            'PY': '',  # 年份
            'DO': '',  # DOI
            'SN': '',  # ISSN
            'VL': '',  # 卷
            'IS': '',  # 期
            'SP': '',  # 起始页
            'EP': '',  # 结束页
            'CR_COUNT': 0,  # 参考文献数量
            'TIMES_CITED': 0,  # 被引次数
            'T2': '',  # 期刊名
        }

        # 提取标题
        ti_match = re.search(r'TI  - (.+)', record)
        if ti_match:
            fields['TI'] = ti_match.group(1).strip()

        # 提取所有作者
        au_matches = re.findall(r'AU  - (.+)', record)
        fields['AU'] = [au.strip() for au in au_matches]

        # 提取摘要（可以跨行）
        ab_match = re.search(r'AB  - (.+?)(?=\n[A-Z]{2}  - |\nER  - |$)', record, re.DOTALL)
        if ab_match:
            fields['AB'] = ab_match.group(1).strip().replace('\n', ' ')

        # 提取关键词
        kw_matches = re.findall(r'KW  - (.+)', record)
        fields['KW'] = [kw.strip() for kw in kw_matches]

        # 提取年份
        py_match = re.search(r'PY  - (\d{4})', record)
        if py_match:
            fields['PY'] = py_match.group(1)

        # 提取 DOI
        do_match = re.search(r'DO  - (.+)', record)
        if do_match:
            fields['DO'] = do_match.group(1).strip()

        # 提取 ISSN
        sn_match = re.search(r'SN  - (.+)', record)
        if sn_match:
            fields['SN'] = sn_match.group(1).strip()

        # 提取卷号
        vl_match = re.search(r'VL  - (.+)', record)
        if vl_match:
            fields['VL'] = vl_match.group(1).strip()

        # 提取期号
        is_match = re.search(r'IS  - (.+)', record)
        if is_match:
            fields['IS'] = is_match.group(1).strip()

        # 提取页码
        sp_match = re.search(r'SP  - (.+)', record)
        if sp_match:
            fields['SP'] = sp_match.group(1).strip()
        ep_match = re.search(r'EP  - (.+)', record)
        if ep_match:
            fields['EP'] = ep_match.group(1).strip()

        # 提取期刊名
        t2_match = re.search(r'T2  - (.+)', record)
        if t2_match:
            fields['T2'] = t2_match.group(1).strip()

        # 提取被引次数（从 N1 字段中提取）
        n1_match = re.search(r'N1  - Times Cited in Web of Science Core Collection:  (\d+)', record)
        if n1_match:
            fields['TIMES_CITED'] = int(n1_match.group(1))

        # 提取参考文献数量（从 N1 字段中提取）
        cr_count_match = re.search(r'Cited Reference Count:  (\d+)', record)
        if cr_count_match:
            fields['CR_COUNT'] = int(cr_count_match.group(1))

        # 只保留有摘要的文献（后续大模型筛选需要摘要）
        if fields['AB']:
            parsed_records.append(fields)

    return parsed_records


def main():
    # 获取所有 RIS 文件
    ris_files = sorted(LITERATURE_DIR.glob("csp_*.ris"))

    print(f"📁 找到 {len(ris_files)} 个 RIS 文件")

    all_records = []

    for ris_file in ris_files:
        print(f"📖 正在解析: {ris_file.name}")
        records = parse_ris_file(ris_file)
        all_records.extend(records)
        print(f"   ✅ 提取了 {len(records)} 篇文献")

    print(f"\n📊 总共提取了 {len(all_records)} 篇文献（含摘要）")

    # 保存为结构化 JSON 文件
    json_path = OUTPUT_DIR / "all_papers.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(all_records, f, ensure_ascii=False, indent=2)

    print(f"💾 已保存到: {json_path}")

    # 打印前2篇的标题作为预览
    print("\n📋 前2篇文献标题预览:")
    for i, record in enumerate(all_records[:2], 1):
        print(f"  {i}. {record['TI']}")
        print(f"    年份: {record['PY']}, 被引: {record['TIMES_CITED']} 次")
        print(f"    摘要长度: {len(record['AB'])} 字符")
        print()


if __name__ == "__main__":
    main()