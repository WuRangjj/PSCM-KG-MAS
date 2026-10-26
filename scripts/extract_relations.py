import json
import time
import re
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv
import os

# 加载环境变量
load_dotenv()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# ========== 配置 ==========
INPUT_PATH = Path(r"C:\Users\20155\dpa4_project\data\parsed\filtered_papers.json")
OUTPUT_PATH = Path(r"C:\Users\20155\dpa4_project\data\parsed\papers_with_relations.json")

client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)

# ========== Prompt 设计 ==========
SYSTEM_PROMPT = """你是一位材料科学专家，擅长从钙钛矿太阳能电池文献中提取结构化知识。

请从文献的标题和摘要中提取以下信息，以 JSON 格式输出：

{
    "main_material": "主要研究的钙钛矿材料名称（如 MAPbI3, FAPbI3, CsPbI3 等）",
    "materials": ["所有提到的钙钛矿材料列表"],
    "properties": [
        {"name": "性能名称", "value": "数值", "unit": "单位"}
    ],
    "methods": ["合成方法", "表征方法"],
    "dopants": ["掺杂元素或化合物"],
    "related_materials": ["相关材料（如电子传输层、空穴传输层等）"],
    "applications": ["应用场景（如太阳能电池、LED、光电探测器等）"]
}

性能名称包括：PCE（光电转换效率）、Voc（开路电压）、Jsc（短路电流）、FF（填充因子）、Bandgap（带隙）、Stability（稳定性）等。

如果某类信息没有提到，返回空列表或 null。
只输出 JSON，不要有其他文字。
"""


def extract_relations(paper):
    """调用 DeepSeek API 从单篇文献中提取关系"""
    title = paper.get('TI', '')
    abstract = paper.get('AB', '')

    user_content = f"""标题: {title}
摘要: {abstract}
"""

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        result = json.loads(response.choices[0].message.content)
        return result
    except Exception as e:
        print(f"   ❌ 抽取失败: {e}")
        return None


def main():
    print("=" * 60)
    print("🔬 钙钛矿文献关系抽取 (DeepSeek API)")
    print("=" * 60)

    # 加载数据
    with open(INPUT_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    kept_papers = data.get('kept_papers', [])
    print(f"\n📚 加载了 {len(kept_papers)} 篇文献")

    # 逐篇抽取
    enriched_papers = []
    total = len(kept_papers)

    for i, paper in enumerate(kept_papers, 1):
        print(f"\n📖 [{i}/{total}] {paper.get('TI', 'N/A')[:50]}...")

        relations = extract_relations(paper)
        if relations:
            paper['extracted_relations'] = relations
            enriched_papers.append(paper)
            print(f"   ✅ 抽取成功")
        else:
            paper['extracted_relations'] = None
            enriched_papers.append(paper)
            print(f"   ⚠️ 跳过")

        # 延迟避免限流
        time.sleep(0.3)

    # 保存结果
    output_data = {
        "total": len(enriched_papers),
        "papers": enriched_papers
    }

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print(f"💾 已保存到: {OUTPUT_PATH}")
    print(f"📊 共处理 {len(enriched_papers)} 篇文献")


if __name__ == "__main__":
    main()