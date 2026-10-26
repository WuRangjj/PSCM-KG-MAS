import json
import re
from pathlib import Path
from neo4j import GraphDatabase

# ========== 配置 ==========
URI = "bolt://localhost:7687"
USERNAME = "neo4j"
PASSWORD = "wr20021218"

DATA_PATH = Path(r"C:\Users\20155\dpa4_project\data\parsed\filtered_papers.json")


def extract_materials(text):
    materials = []
    patterns = [
        r'([A-Z][a-z]?[A-Z]?[a-z]?Pb[A-Z]?[a-z]?[0-9]?)',
        r'(MAPbI[0-9])', r'(FAPbI[0-9])', r'(CsPb[A-Z][a-z]?[0-9]?)',
        r'(CH3NH3PbI[0-9])', r'(HC(NH2)2PbI[0-9])',
        r'([A-Z][a-z]?[A-Z]?[a-z]?[A-Z]?[a-z]?Sn[A-Z]?[a-z]?[0-9]?)',
        r'(SrTiO[0-9])', r'(BaTiO[0-9])', r'(LaMnO[0-9])',
    ]
    for pattern in patterns:
        found = re.findall(pattern, text)
        materials.extend(found)
    return list(set(materials))


def extract_properties(text):
    properties = []
    patterns = {
        'PCE': r'(\d+\.?\d*)\s*%?\s*(?:PCE|power conversion efficiency|efficiency)',
        'Jsc': r'(\d+\.?\d*)\s*(?:mA/cm2|mA cm-2|mA/cm²)\s*(?:Jsc|short-circuit current)',
        'Voc': r'(\d\.?\d*)\s*(?:V|volt)\s*(?:Voc|open-circuit voltage)',
        'FF': r'(0\.\d+|\d+\.?\d*%)\s*(?:FF|fill factor)',
        'Bandgap': r'(\d\.?\d*)\s*(?:eV|electron volt)\s*(?:bandgap|band gap|optical gap)',
        'Stability': r'(\d+)\s*(?:h|hour|day)\s*(?:stability|degradation|T50)',
    }
    for key, pattern in patterns.items():
        found = re.search(pattern, text, re.IGNORECASE)
        if found:
            properties.append(f"{key}={found.group(1)}")
    return properties


def extract_methods(text):
    methods = []
    method_list = [
        'spin-coating', 'spin coating', 'thermal evaporation', 'sputtering',
        'CVD', 'PVD', 'ALD', 'PLD', 'sol-gel', 'sol gel',
        'hydrothermal', 'solution process', 'solution processing',
        'XRD', 'SEM', 'TEM', 'AFM', 'XPS', 'UPS', 'SCLC',
        'UV-vis', 'PL', 'TRPL', 'EQE', 'J-V', 'EIS',
        'GIWAXS', 'GISAXS', 'TOF-SIMS', 'SSNMR',
        'DFT', 'first-principles', 'molecular dynamics', 'MD',
        'machine learning', 'ML', 'AI'
    ]
    for method in method_list:
        if method in text.lower():
            methods.append(method)
    return list(set(methods))


def main():
    with open(DATA_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    kept_papers = data.get('kept_papers', [])
    print(f"📚 加载了 {len(kept_papers)} 篇文献")

    driver = GraphDatabase.driver(URI, auth=(USERNAME, PASSWORD))
    with driver.session() as session:
        print("✅ 连接成功，开始构建知识图谱...")

        for i, paper in enumerate(kept_papers, 1):
            title = paper.get('TI', '')
            abstract = paper.get('AB', '')
            authors = paper.get('AU', [])
            year = paper.get('PY', '')
            doi = paper.get('DO', f"unknown_{i}")
            journal = paper.get('T2', '')
            times_cited = paper.get('TIMES_CITED', 0)

            # 1. 创建 Publication 节点
            session.run("""
                MERGE (pub:Publication {doi: $doi})
                SET pub.title = $title,
                    pub.journal = $journal,
                    pub.year = $year,
                    pub.times_cited = $times_cited,
                    pub.authors = $authors
            """, doi=doi, title=title, journal=journal, year=year,
                        times_cited=times_cited, authors=authors)

            full_text = title + " " + abstract
            materials = extract_materials(full_text)
            for mat in materials:
                if len(mat) > 1:
                    session.run("""
                        MERGE (m:Material {name: $name})
                        SET m.category = 'Perovskite'
                    """, name=mat)
                    session.run("""
                        MATCH (pub:Publication {doi: $doi})
                        MATCH (m:Material {name: $name})
                        MERGE (pub)-[:STUDIES]->(m)
                    """, doi=doi, name=mat)

            properties = extract_properties(full_text)
            for prop in properties:
                session.run("MERGE (p:Property {name: $name})", name=prop)
                for mat in materials:
                    if len(mat) > 1:
                        session.run("""
                            MATCH (m:Material {name: $mat})
                            MATCH (p:Property {name: $prop})
                            MERGE (m)-[:HAS_PROPERTY]->(p)
                        """, mat=mat, prop=prop)

            methods = extract_methods(full_text)
            for method in methods:
                session.run("MERGE (m:Method {name: $name})", name=method)
                for mat in materials:
                    if len(mat) > 1:
                        session.run("""
                            MATCH (mat:Material {name: $mat})
                            MATCH (met:Method {name: $method})
                            MERGE (mat)-[:CHARACTERIZED_BY]->(met)
                        """, mat=mat, method=method)

            if i % 50 == 0:
                print(f"📖 已处理 {i}/{len(kept_papers)} 篇文献")

        driver.close()
        print("✅ 知识图谱构建完成！")


if __name__ == "__main__":
    main()