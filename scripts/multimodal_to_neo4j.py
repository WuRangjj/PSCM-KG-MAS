import json
from pathlib import Path
from neo4j import GraphDatabase

# ========== 配置 ==========
URI = "bolt://localhost:7687"
USERNAME = "neo4j"
PASSWORD = "wr20021218"

RESULTS_PATH = Path(r"C:\Users\20155\dpa4_project\data\multimodal_output\multimodal_results_v2.json")


def main():
    # 加载多模态结果
    with open(RESULTS_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    driver = GraphDatabase.driver(URI, auth=(USERNAME, PASSWORD))

    with driver.session() as session:
        total_evidence = 0

        for pdf_name, info in data.items():
            # 从文件名提取 DOI（去掉 .pdf）
            doi = pdf_name.replace('.pdf', '').replace('_', '/')

            for item in info.get('analyzed', []):
                # 解析 analysis 内容
                analysis_str = item.get('analysis', '{}')
                try:
                    analysis = json.loads(analysis_str)
                except:
                    analysis = {"extracted_info": analysis_str[:200]}

                image_type = analysis.get('image_type', '未知')
                extracted_info = analysis.get('extracted_info', '')
                numerical_values = analysis.get('numerical_values', {})

                # 创建 Evidence 节点，关联到 Publication
                session.run("""
                    MATCH (pub:Publication {doi: $doi})
                    MERGE (e:Evidence {
                        image: $image,
                        source_pdf: $pdf_name
                    })
                    SET e.image_type = $image_type,
                        e.extracted_info = $extracted_info,
                        e.numerical_values = $numerical_values
                    MERGE (pub)-[:HAS_EVIDENCE]->(e)
                """,
                            doi=doi,
                            image=item.get('image', ''),
                            pdf_name=pdf_name,
                            image_type=image_type,
                            extracted_info=extracted_info,
                            numerical_values=json.dumps(numerical_values, ensure_ascii=False)
                            )
                total_evidence += 1

        print(f"✅ 共创建 {total_evidence} 条多模态证据")

        # 验证
        result = session.run("MATCH (e:Evidence) RETURN count(e) AS count")
        print(f"📊 当前 Evidence 节点总数: {result.single()['count']}")

    driver.close()


if __name__ == "__main__":
    main()