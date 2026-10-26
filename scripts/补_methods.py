import json
from pathlib import Path
from neo4j import GraphDatabase

# ========== 配置 ==========
URI = "bolt://localhost:7687"
USERNAME = "neo4j"
PASSWORD = "wr20021218"

RELATIONS_PATH = Path(r"C:\Users\20155\dpa4_project\data\parsed\papers_with_relations.json")

def main():
    print("=" * 60)
    print("🔧 补充 CHARACTERIZED_BY 关系")
    print("=" * 60)

    # 加载关系数据
    with open(RELATIONS_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    papers = data.get('papers', [])
    print(f"📚 加载了 {len(papers)} 篇文献")

    driver = GraphDatabase.driver(URI, auth=(USERNAME, PASSWORD))

    with driver.session() as session:
        total_methods = 0

        for i, paper in enumerate(papers, 1):
            relations = paper.get('extracted_relations')
            if not relations:
                continue

            main_material = relations.get('main_material')
            methods = relations.get('methods', [])

            # 如果没有主材料或方法，跳过
            if not main_material or not methods:
                continue

            # 确保主材料节点存在
            session.run(
                "MERGE (m:Material {name: $name}) SET m.category = 'Perovskite'",
                name=main_material
            )

            # 为每个方法建立 CHARACTERIZED_BY 关系
            for method in methods:
                if not method:
                    continue
                session.run("""
                    MATCH (m:Material {name: $mat})
                    MERGE (met:Method {name: $method})
                    MERGE (m)-[:CHARACTERIZED_BY]->(met)
                """, mat=main_material, method=method)
                total_methods += 1

            if i % 50 == 0:
                print(f"📖 已处理 {i}/{len(papers)} 篇文献")

        print(f"\n✅ 共创建 {total_methods} 条 CHARACTERIZED_BY 关系")

        # 验证
        result = session.run("MATCH ()-[r:CHARACTERIZED_BY]->() RETURN count(r) AS total")
        total = result.single()["total"]
        print(f"📊 当前 CHARACTERIZED_BY 关系总数: {total}")

    driver.close()
    print("✅ 完成！")

if __name__ == "__main__":
    main()