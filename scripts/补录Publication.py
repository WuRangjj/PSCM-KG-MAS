import json
from neo4j import GraphDatabase

URI = "bolt://localhost:7687"
USER = "neo4j"
PASS = "wr20021218"

with open('C:/Users/20155/dpa4_project/data/parsed/filtered_papers.json', encoding='utf-8') as f:
    data = json.load(f)
    papers = data.get('kept_papers', [])

driver = GraphDatabase.driver(URI, auth=(USER, PASS))

created = 0
skipped = 0

with driver.session() as session:
    for i, paper in enumerate(papers, 1):
        doi = paper.get('DO')
        if not doi:
            continue

        # 检查是否已存在
        result = session.run("MATCH (p:Publication {doi: $doi}) RETURN p", doi=doi)
        if result.single():
            skipped += 1
            continue

        # 创建 Publication 节点
        session.run("""
            CREATE (p:Publication {
                doi: $doi,
                title: $title,
                journal: $journal,
                year: $year,
                times_cited: $times_cited
            })
        """, doi=doi, title=paper.get('TI', ''), journal=paper.get('T2', ''),
                    year=paper.get('PY', ''), times_cited=paper.get('TIMES_CITED', 0))
        created += 1

        if created % 50 == 0:
            print(f"已补录 {created} 篇")

driver.close()
print(f"补录完成：新增 {created} 篇，跳过 {skipped} 篇")