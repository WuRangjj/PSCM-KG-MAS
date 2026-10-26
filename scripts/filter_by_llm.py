import json
import time
from pathlib import Path
from openai import OpenAI

# ========== 配置 ==========
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
DEEPSEEK_API_KEY = os.environ["DEEPSEEK_API_KEY"]
INPUT_PATH = Path(r"C:\Users\20155\dpa4_project\data\parsed\all_papers.json")
OUTPUT_PATH = Path(r"C:\Users\20155\dpa4_project\data\parsed\filtered_papers.json")

# 初始化 DeepSeek 客户端
client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)

# ========== 筛选提示词 ==========
SYSTEM_PROMPT = """你是一位材料科学专家，擅长判断文献是否以钙钛矿（perovskite）材料为核心研究对象。

判断标准：
1. 文献的主要研究内容必须是钙钛矿材料（包括卤化物钙钛矿、氧化物钙钛矿）
2. 钙钛矿材料必须是全文的核心（占主要内容80%以上），而不是仅在背景中提及
3. 涉及太阳能电池、发光、催化等应用场景的钙钛矿研究都算

输出格式（JSON）：
{
    "decision": "KEEP" 或 "EXCLUDE",
    "confidence": 0.95,
    "reason": "简要判断理由"
}
"""


def filter_single_paper(paper):
    """调用 DeepSeek API 判断单篇文献是否保留"""

    # 构建用户输入
    user_content = f"""标题: {paper.get('TI', 'N/A')}
摘要: {paper.get('AB', 'N/A')}
关键词: {', '.join(paper.get('KW', [])[:5])}
年份: {paper.get('PY', 'N/A')}
期刊: {paper.get('T2', 'N/A')}

请判断这篇文献是否以钙钛矿材料为核心研究内容。"""

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
        print(f"   ❌ API 调用失败: {e}")
        return {"decision": "ERROR", "confidence": 0, "reason": str(e)}


def main():
    print("=" * 60)
    print("🔍 钙钛矿文献语义筛选器 (DeepSeek API)")
    print("=" * 60)

    # 1. 加载数据
    with open(INPUT_PATH, 'r', encoding='utf-8') as f:
        papers = json.load(f)

    print(f"\n📚 加载了 {len(papers)} 篇文献")

    # 2. 逐篇筛选
    kept = []
    excluded = []
    errors = []

    for i, paper in enumerate(papers, 1):
        print(f"\n📖 [{i}/{len(papers)}] {paper.get('TI', 'N/A')[:60]}...")

        result = filter_single_paper(paper)

        # 记录筛选结果
        paper['filter_result'] = result
        paper['filter_decision'] = result.get('decision', 'ERROR')
        paper['filter_confidence'] = result.get('confidence', 0)
        paper['filter_reason'] = result.get('reason', '')

        if result.get('decision') == 'KEEP':
            kept.append(paper)
            print(f"   ✅ KEEP (置信度: {result.get('confidence', 0):.2f})")
        elif result.get('decision') == 'EXCLUDE':
            excluded.append(paper)
            print(f"   ❌ EXCLUDE (置信度: {result.get('confidence', 0):.2f})")
        else:
            errors.append(paper)
            print(f"   ⚠️ ERROR")

        # 添加延迟，避免 API 限流
        time.sleep(0.5)

    # 3. 保存结果
    output_data = {
        "summary": {
            "total": len(papers),
            "kept": len(kept),
            "excluded": len(excluded),
            "errors": len(errors)
        },
        "kept_papers": kept,
        "excluded_papers": excluded,
        "error_papers": errors
    }

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    # 4. 输出统计
    print("\n" + "=" * 60)
    print("📊 筛选结果统计")
    print("=" * 60)
    print(f"  总文献数: {len(papers)}")
    print(f"  ✅ KEEP: {len(kept)} 篇")
    print(f"  ❌ EXCLUDE: {len(excluded)} 篇")
    print(f"  ⚠️ ERROR: {len(errors)} 篇")
    print(f"\n💾 结果已保存到: {OUTPUT_PATH}")

    # 打印前3篇保留的文献标题
    if kept:
        print("\n📋 保留文献示例 (前3篇):")
        for i, paper in enumerate(kept[:3], 1):
            print(f"  {i}. {paper.get('TI', 'N/A')[:80]}")
            print(f"     理由: {paper.get('filter_reason', 'N/A')[:100]}")


if __name__ == "__main__":
    main()