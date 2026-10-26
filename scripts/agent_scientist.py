import json
from pathlib import Path
from neo4j import GraphDatabase
from openai import OpenAI
from dotenv import load_dotenv
import os

# 加载环境变量
load_dotenv()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# ========== 配置 ==========
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "wr20021218"

# ========== 初始化客户端 ==========
neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
llm_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")


# ========== KG-Miner：智能体1 - 检索图谱 ==========
class KG_Miner:
    """负责查询知识图谱，返回证据"""

    def __init__(self, driver):
        self.driver = driver

    def get_material_properties(self, material_name):
        with self.driver.session() as session:
            result = session.run(
                "MATCH (m:Material {name: $name})-[:HAS_PROPERTY]->(p:Property) "
                "RETURN p.name AS property",
                name=material_name
            )
            return [record["property"] for record in result]

    def get_material_methods(self, material_name):
        with self.driver.session() as session:
            result = session.run(
                "MATCH (m:Material {name: $name})-[:CHARACTERIZED_BY]->(met:Method) "
                "RETURN met.name AS method",
                name=material_name
            )
            return [record["method"] for record in result]

    def get_material_applications(self, material_name):
        with self.driver.session() as session:
            result = session.run(
                "MATCH (m:Material {name: $name})-[:USED_IN]->(a:Application) "
                "RETURN a.name AS application",
                name=material_name
            )
            return [record["application"] for record in result]

    def get_dopants(self, material_name):
        with self.driver.session() as session:
            result = session.run(
                "MATCH (m:Material {name: $name})-[:DOPED_WITH]->(d:Material) "
                "RETURN d.name AS dopant",
                name=material_name
            )
            return [record["dopant"] for record in result]

    def search_materials(self, keyword):
        with self.driver.session() as session:
            result = session.run(
                "MATCH (m:Material) WHERE m.name CONTAINS $keyword "
                "RETURN m.name AS name LIMIT 10",
                keyword=keyword
            )
            return [record["name"] for record in result]

    def query_by_cypher(self, cypher_query):
        with self.driver.session() as session:
            result = session.run(cypher_query)
            return [record.data() for record in result]


# ========== Scientist：智能体2 - 推理 ==========
class Scientist:
    """基于 KG-Miner 返回的证据，进行科学推理"""

    def __init__(self, llm_client):
        self.llm = llm_client

    def analyze_material(self, material_name, kg_miner):
        print(f"🔍 正在查询图谱: {material_name}")
        properties = kg_miner.get_material_properties(material_name)
        methods = kg_miner.get_material_methods(material_name)
        applications = kg_miner.get_material_applications(material_name)
        dopants = kg_miner.get_dopants(material_name)

        if not properties and not methods:
            print(f"⚠️ 未找到 '{material_name}'，尝试模糊搜索...")
            suggestions = kg_miner.search_materials(material_name)
            if suggestions:
                print(f"💡 建议的材料: {suggestions[:5]}")
                return {
                    "material": material_name,
                    "found": False,
                    "suggestions": suggestions[:5],
                    "message": f"未找到 '{material_name}'，以下材料名相似: {suggestions[:5]}"
                }
            else:
                return {
                    "material": material_name,
                    "found": False,
                    "message": f"图谱中未找到 '{material_name}'，也没有相似的记录"
                }

        evidence = {
            "properties": properties[:20],
            "methods": methods[:10],
            "applications": applications[:10],
            "dopants": dopants[:10]
        }

        prompt = f"""你是一位钙钛矿太阳能电池材料科学家。

请基于以下证据，对材料 **{material_name}** 做一份简要的分析报告。

【证据】
- 性能数据: {evidence['properties'] if evidence['properties'] else '无记录'}
- 制备/表征方法: {evidence['methods'] if evidence['methods'] else '无记录'}
- 应用: {evidence['applications'] if evidence['applications'] else '无记录'}
- 掺杂: {evidence['dopants'] if evidence['dopants'] else '无记录'}

请输出一份 JSON 格式的报告，包含：
1. summary: 一句话总结这个材料
2. key_findings: 3-5个关键发现（从证据中提取）
3. limitations: 当前证据的不足（哪些信息缺失）
4. source_count: 证据的总条数（统计上面四个列表的总数）
"""

        try:
            response = self.llm.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "你是材料科学家，只输出 JSON。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            report = json.loads(response.choices[0].message.content)
            report["material"] = material_name
            report["found"] = True
            report["evidence"] = evidence
            return report

        except Exception as e:
            return {
                "material": material_name,
                "found": True,
                "error": str(e),
                "evidence": evidence,
                "message": "大模型生成失败，但证据已检索到"
            }


# ========== Critic：智能体3 - 审查 ==========
class Critic:
    """负责审查 Scientist 的结论，核对证据，指出问题"""

    def __init__(self, llm_client):
        self.llm = llm_client

    def review(self, scientist_report, kg_miner):
        material = scientist_report.get("material", "")
        evidence = scientist_report.get("evidence", {})
        summary = scientist_report.get("summary", "")
        findings = scientist_report.get("key_findings", [])

        prompt = f"""你是一位严谨的同行评审专家，专门审查材料科学分析报告。

你的任务是：对照原始证据，检查 Scientist 的分析报告是否准确、是否有遗漏、是否有夸大。

【材料】{material}

【Scientist 的结论】
- 总结: {summary}
- 关键发现: {findings}

【原始证据】
- 性能数据: {evidence.get('properties', [])[:15]}
- 制备/表征方法: {evidence.get('methods', [])[:10]}
- 应用: {evidence.get('applications', [])[:10]}
- 掺杂: {evidence.get('dopants', [])[:10]}

请输出 JSON 格式的审查意见：
{{
    "is_accurate": true/false,
    "issues": ["问题1", "问题2"],
    "missing_evidence": ["缺失的证据类型1", "缺失的证据类型2"],
    "suggestion": "改进建议（一句话）",
    "overall_verdict": "PASS" 或 "REVISE"
}}
"""

        try:
            response = self.llm.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "你是严格的同行评审专家，只输出 JSON。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            review_result = json.loads(response.choices[0].message.content)
            review_result["material"] = material
            return review_result
        except Exception as e:
            return {
                "material": material,
                "is_accurate": False,
                "issues": [f"审查失败: {str(e)}"],
                "missing_evidence": [],
                "suggestion": "请人工核对",
                "overall_verdict": "ERROR"
            }


# ========== Editor：智能体4 - 综合报告 ==========
class Editor:
    """汇总 Scientist 报告和 Critic 审查意见，生成最终报告"""

    def __init__(self, llm_client):
        self.llm = llm_client

    def generate_final_report(self, scientist_report, review_result):
        """基于 Scientist 报告和 Critic 审查意见，输出最终报告"""

        material = scientist_report.get("material", "")
        summary = scientist_report.get("summary", "")
        findings = scientist_report.get("key_findings", [])
        limitations = scientist_report.get("limitations", [])
        evidence = scientist_report.get("evidence", {})
        source_count = scientist_report.get("source_count", 0)

        verdict = review_result.get("overall_verdict", "UNKNOWN")
        issues = review_result.get("issues", [])
        missing_evidence = review_result.get("missing_evidence", [])
        suggestion = review_result.get("suggestion", "")

        prompt = f"""你是一位资深材料科学编辑，负责将科研分析整理成规范的技术报告。

请基于以下信息，生成一份关于材料 **{material}** 的完整最终报告。

【Scientist 的分析】
- 总结: {summary}
- 关键发现: {findings}
- 当前局限: {limitations}
- 证据总数: {source_count} 条

【Critic 的审查意见】
- 审查结论: {verdict}
- 指出的问题: {issues if issues else '无'}
- 缺失证据: {missing_evidence if missing_evidence else '无'}
- 改进建议: {suggestion if suggestion else '无需改进'}

请输出 JSON 格式的最终报告，包含：
1. material: 材料名称
2. verdict: 最终结论（"批准" 或 "需修改" 或 "证据不足"）
3. summary: 重新撰写的摘要（综合两边意见）
4. key_findings: 确凿的关键发现（只列有证据支撑的）
5. contested_points: 有争议的点（Scientist 说了但 Critic 质疑的）
6. evidence_summary: 证据概况（总数、类型分布）
7. next_steps: 后续建议（基于 Critic 的建议）
"""

        try:
            response = self.llm.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "你是一位资深科学编辑，只输出 JSON。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            final_report = json.loads(response.choices[0].message.content)
            return final_report
        except Exception as e:
            return {
                "material": material,
                "verdict": "ERROR",
                "summary": f"报告生成失败: {str(e)}",
                "key_findings": [],
                "contested_points": [],
                "evidence_summary": {},
                "next_steps": "请人工核对"
            }


# ========== 主程序 ==========
def main():
    print("=" * 60)
    print("🧠 多智能体系统演示 (Scientist + Critic + Editor + KG-Miner)")
    print("=" * 60)

    kg_miner = KG_Miner(neo4j_driver)
    scientist = Scientist(llm_client)
    critic = Critic(llm_client)
    editor = Editor(llm_client)

    test_materials = ["MAPbI3", "FAPbI3", "CsPbCl3"]

    for material in test_materials:
        print("\n" + "=" * 50)
        print(f"📌 分析材料: {material}")
        print("=" * 50)

        print("\n🔬 Scientist 正在分析...")
        scientist_report = scientist.analyze_material(material, kg_miner)

        if not scientist_report.get("found"):
            print(f"❌ 未找到材料: {material}")
            continue

        print("\n🔍 Critic 正在审查...")
        review_result = critic.review(scientist_report, kg_miner)

        print("\n📝 Editor 正在生成最终报告...")
        final_report = editor.generate_final_report(scientist_report, review_result)

        print("\n📄 === 最终报告 ===")
        print(json.dumps(final_report, ensure_ascii=False, indent=2))
        print("=" * 40)

    neo4j_driver.close()
    print("\n" + "=" * 60)
    print("✅ 多智能体演示完成！")


if __name__ == "__main__":
    main()