import json
from pathlib import Path
from neo4j import GraphDatabase

# ========== 配置 ==========
URI = "bolt://localhost:7687"
USERNAME = "neo4j"
PASSWORD = "wr20021218"

RELATIONS_PATH = Path(r"C:\Users\20155\dpa4_project\data\parsed\papers_with_relations.json")

# ========== 同义词映射（合并同名材料） ==========
SYNONYM_MAP = {
    "MAPbI3": ["MAPbI3", "CH3NH3PbI3", "Methylammonium lead iodide", "MAPbI", "CH3NH3PBI3", "MAPbIx"],
    "FAPbI3": ["FAPbI3", "HC(NH2)2PbI3", "Formamidinium lead iodide", "FAPbI", "FA0.85Cs0.15PbI3"],
    "CsPbI3": ["CsPbI3", "Cesium lead iodide"],
    "CsPbBr3": ["CsPbBr3", "Cesium lead bromide"],
    "CsPbI2Br": ["CsPbI2Br"],
    "CsPbIBr2": ["CsPbIBr2"],
    "CsSnI3": ["CsSnI3"],
    "FASnI3": ["FASnI3"],
    "MAPbBr3": ["MAPbBr3", "CH3NH3PbBr3"],
    "MAPbCl3": ["MAPbCl3", "CH3NH3PbCl3"],
}


def get_canonical_name(name):
    """根据同义词映射，返回规范化名称"""
    if not name:
        return name
    name_clean = name.strip()
    for canonical, variants in SYNONYM_MAP.items():
        if name_clean in variants:
            return canonical
    return name_clean


def clear_old_relations():
    """清空旧的关系（保留节点），避免重复"""
    driver = GraphDatabase.driver(URI, auth=(USERNAME, PASSWORD))
    with driver.session() as session:
        session.run("MATCH ()-[r]->() DELETE r")
        print("✅ 已清空旧关系")
    driver.close()


def align_and_write():
    """执行实体对齐并写入新关系"""

    # 1. 加载抽取的关系数据
    with open(RELATIONS_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    papers = data.get('papers', [])
    print(f"📚 加载了 {len(papers)} 篇带关系的文献")

    driver = GraphDatabase.driver(URI, auth=(USERNAME, PASSWORD))

    with driver.session() as session:
        # 可选：清空旧关系（如果你担心重复，可以取消注释）
        # clear_old_relations()

        # 获取所有现有 Material 节点
        result = session.run("MATCH (m:Material) RETURN m.name AS name")
        existing_materials = [record["name"] for record in result]
        print(f"📊 当前有 {len(existing_materials)} 个 Material 节点")

        # 统计
        total_props = 0
        total_methods = 0
        total_dopants = 0
        total_apps = 0
        total_related = 0

        for i, paper in enumerate(papers, 1):
            relations = paper.get('extracted_relations')
            if not relations:
                continue

            main_material = relations.get('main_material')
            if main_material:
                main_material = get_canonical_name(main_material)
                # 确保主材料节点存在
                session.run("MERGE (m:Material {name: $name}) SET m.category = 'Perovskite'", name=main_material)

            materials = relations.get('materials', [])
            materials = [get_canonical_name(m) for m in materials if m]
            for mat in materials:
                if mat:
                    session.run("MERGE (m:Material {name: $name}) SET m.category = 'Perovskite'", name=mat)

            # 1. 建立材料-性能关系
            properties = relations.get('properties', [])
            for prop in properties:
                prop_name = prop.get('name', '')
                prop_value = prop.get('value', '')
                prop_unit = prop.get('unit', '')
                if not prop_name or not prop_value:
                    continue
                full_prop = f"{prop_name}={prop_value}{prop_unit}"

                # 关联到主材料
                if main_material:
                    session.run("""
                        MATCH (m:Material {name: $mat})
                        MERGE (p:Property {name: $prop})
                        MERGE (m)-[:HAS_PROPERTY]->(p)
                    """, mat=main_material, prop=full_prop)
                    total_props += 1

                # 关联到所有材料
                for mat in materials:
                    if mat and mat != main_material:
                        session.run("""
                            MATCH (m:Material {name: $mat})
                            MERGE (p:Property {name: $prop})
                            MERGE (m)-[:HAS_PROPERTY]->(p)
                        """, mat=mat, prop=full_prop)
                        total_props += 1

            # 2. 建立材料-方法关系
            methods = relations.get('methods', [])
            for method in methods:
                if not method:
                    continue
                if main_material:
                    session.run("""
                        MATCH (m:Material {name: $mat})
                        MERGE (met:Method {name: $method})
                        MERGE (m)-[:CHARACTERIZED_BY]->(met)
                    """, mat=main_material, method=method)
                    total_methods += 1
                for mat in materials:
                    if mat and mat != main_material:
                        session.run("""
                            MATCH (m:Material {name: $mat})
                            MERGE (met:Method {name: $method})
                            MERGE (m)-[:CHARACTERIZED_BY]->(met)
                        """, mat=mat, method=method)
                        total_methods += 1

            # 3. 建立掺杂关系
            dopants = relations.get('dopants', [])
            for dopant in dopants:
                if not dopant:
                    continue
                dopant = get_canonical_name(dopant)
                if main_material:
                    session.run("""
                        MATCH (m:Material {name: $mat})
                        MERGE (d:Material {name: $dopant, category: 'Dopant'})
                        MERGE (m)-[:DOPED_WITH]->(d)
                    """, mat=main_material, dopant=dopant)
                    total_dopants += 1

            # 4. 建立应用关系
            applications = relations.get('applications', [])
            for app in applications:
                if not app:
                    continue
                if main_material:
                    session.run("""
                        MATCH (m:Material {name: $mat})
                        MERGE (a:Application {name: $app})
                        MERGE (m)-[:USED_IN]->(a)
                    """, mat=main_material, app=app)
                    total_apps += 1

            # 5. 建立相关材料关系
            related = relations.get('related_materials', [])
            for rel in related:
                if not rel:
                    continue
                rel = get_canonical_name(rel)
                if main_material and rel:
                    session.run("""
                        MATCH (m1:Material {name: $main})
                        MERGE (m2:Material {name: $related})
                        MERGE (m1)-[:RELATED_TO]->(m2)
                    """, main=main_material, related=rel)
                    total_related += 1

            if i % 50 == 0:
                print(f"📖 已处理 {i}/{len(papers)} 篇文献")

        print("\n" + "=" * 60)
        print("📊 写入统计")
        print("=" * 60)
        print(f"  HAS_PROPERTY 关系: {total_props} 条")
        print(f"  CHARACTERIZED_BY 关系: {total_methods} 条")
        print(f"  DOPED_WITH 关系: {total_dopants} 条")
        print(f"  USED_IN 关系: {total_apps} 条")
        print(f"  RELATED_TO 关系: {total_related} 条")

        # 最终统计
        result = session.run("""
            MATCH (n) RETURN labels(n) AS label, count(n) AS count
            ORDER BY count DESC
        """)
        print("\n📊 节点统计:")
        for record in result:
            print(f"  {record['label']}: {record['count']}")

        result = session.run("MATCH ()-[r]->() RETURN count(r) AS total")
        total_rels = result.single()["total"]
        print(f"\n📊 总关系数: {total_rels}")

    driver.close()
    print("\n✅ 全部完成！")


if __name__ == "__main__":
    print("=" * 60)
    print("🔗 关系写入 Neo4j (含实体对齐)")
    print("=" * 60)
    align_and_write()