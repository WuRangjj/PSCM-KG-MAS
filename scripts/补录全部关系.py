import json
from neo4j import GraphDatabase

URI = "bolt://localhost:7687"
USER = "neo4j"
PASS = "wr20021218"

with open('C:/Users/20155/dpa4_project/data/parsed/papers_with_relations.json', encoding='utf-8') as f:
    data = json.load(f)
    papers = data.get('papers', [])

driver = GraphDatabase.driver(URI, auth=(USER, PASS))

material_count = 0
property_count = 0
method_count = 0
study_count = 0
prop_rel_count = 0
method_rel_count = 0

with driver.session() as session:
    for paper in papers:
        doi = paper.get('DO')
        if not doi:
            continue

        relations = paper.get('extracted_relations')
        if not relations:
            continue

        # 1. 材料
        materials = relations.get('materials', [])
        main_material = relations.get('main_material')
        all_materials = list(set(materials + ([main_material] if main_material else [])))
        all_materials = [m for m in all_materials if m]

        for mat_name in all_materials:
            session.run("""
                MERGE (m:Material {name: $name})
                SET m.category = 'Perovskite'
            """, name=mat_name)
            material_count += 1

            session.run("""
                MATCH (p:Publication {doi: $doi})
                MATCH (m:Material {name: $name})
                MERGE (p)-[:STUDIES]->(m)
            """, doi=doi, name=mat_name)
            study_count += 1

        # 2. 性能
        properties = relations.get('properties', [])
        for prop in properties:
            prop_name = prop.get('name', '')
            prop_value = prop.get('value', '')
            prop_unit = prop.get('unit', '')
            if not prop_name or not prop_value:
                continue
            full_prop = f"{prop_name}={prop_value}{prop_unit}"

            session.run("MERGE (p:Property {name: $name})", name=full_prop)
            property_count += 1

            for mat_name in all_materials:
                session.run("""
                    MATCH (m:Material {name: $mat})
                    MATCH (prop:Property {name: $prop})
                    MERGE (m)-[:HAS_PROPERTY]->(prop)
                """, mat=mat_name, prop=full_prop)
                prop_rel_count += 1

        # 3. 方法
        methods = relations.get('methods', [])
        for method in methods:
            if not method:
                continue
            session.run("MERGE (m:Method {name: $name})", name=method)
            method_count += 1

            for mat_name in all_materials:
                session.run("""
                    MATCH (mat:Material {name: $mat})
                    MATCH (met:Method {name: $method})
                    MERGE (mat)-[:CHARACTERIZED_BY]->(met)
                """, mat=mat_name, method=method)
                method_rel_count += 1

driver.close()

print("=" * 50)
print("补录完成！")
print(f"材料节点新增/合并: {material_count}")
print(f"性能节点新增/合并: {property_count}")
print(f"方法节点新增/合并: {method_count}")
print(f"STUDIES 关系新增: {study_count}")
print(f"HAS_PROPERTY 关系新增: {prop_rel_count}")
print(f"CHARACTERIZED_BY 关系新增: {method_rel_count}")