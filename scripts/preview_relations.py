import json
from pathlib import Path

RELATIONS_PATH = Path(r"C:\Users\20155\dpa4_project\data\parsed\papers_with_relations.json")

with open(RELATIONS_PATH, 'r', encoding='utf-8') as f:
    data = json.load(f)

papers = data.get('papers', [])
print(f"总文献数: {len(papers)}")

# 找第一个有关系的文献
for i, paper in enumerate(papers):
    if paper.get('extracted_relations'):
        print(f"\n第 {i+1} 篇文献:")
        print(f"标题: {paper.get('TI', 'N/A')}")
        print(f"关系内容: {paper.get('extracted_relations')}")
        break