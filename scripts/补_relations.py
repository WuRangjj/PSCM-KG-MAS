# -*- coding: utf-8 -*-
"""
Manual completion: Literature -> Material relationships
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from neo4j import GraphDatabase

URI = "bolt://localhost:7687"
USERNAME = "neo4j"
PASSWORD = "wr20021218"

# material synonym map
SYNONYM_MAP = {
    "MAPbI3": ["MAPbI3", "CH3NH3PbI3", "Methylammonium lead iodide", "MAPbI", "CH3NH3PBI3", "MAPbIx"],
    "FAPbI3": ["FAPbI3", "HC(NH2)2PbI3", "Formamidinium lead iodide", "FAPbI", "FA0.85Cs0.15PbI3"],
    "CsPbI3": ["CsPbI3", "Cesium lead iodide"],
}

def get_canonical_name(name):
    if not name:
        return name
    name_clean = name.strip()
    for canonical, variants in SYNONYM_MAP.items():
        if name_clean in variants:
            return canonical
    return name_clean

# ========================================
# Manual mapping table: (DOI, [materials], skip?)
# ========================================
PAPER_MATERIAL_MAP = [
    ("10.1126/science.aaa0472",     ["MAPbI3"],                         False),
    ("10.1021/acs.chemrev.8b00539", [],                                 True),   # review
    ("10.1126/science.aai9081",     ["MAPbI3", "FAPbI3"],               False),
    ("10.1021/jacs.5b04930",        ["MAPbI3"],                         False),
    ("10.1021/acs.chemmater.5b04107", ["FAPbI3", "CsPbI3"],             False),
    ("10.1021/jacs.5b03796",        [],                                 True),   # 2D perovskite, skip
    ("10.1038/NNANO.2015.230",      ["MAPbI3"],                         False),
    ("10.1016/j.joule.2019.06.014", ["MAPbI3"],                         False),
    ("10.1038/ncomms8747",          ["MAPbI3"],                         False),
    ("10.1021/jacs.5b01994",        ["MAPbI3"],                         False),
    ("10.1038/s41467-019-08507-4",  ["MAPbI3", "FAPbI3"],               False),
    ("10.1021/acs.chemrev.0c01006", [],                                 True),   # review
    ("10.1002/anie.201601757",      [],                                 True),   # review
    ("10.1021/acs.jpcc.6b01728",    ["MAPbI3"],                         False),
    ("10.1021/acs.chemmater.5b01991", ["MAPbI3"],                       False),
    ("10.1039/c6ta08783c",          ["MAPbI3"],                         False),
    ("10.1007/s40820-019-0244-6",   [],                                 True),   # review
    ("10.1021/jp510837q",           ["MAPbI3"],                         False),
    ("10.1021/acs.nanolett.6b03119", ["CH3NH3PbI3"],                    False),
    ("10.1038/s41467-020-20749-1",  ["CsPbI3", "FAPbI3"],               False),
]


def main():
    print("=" * 70)
    print("[Manual] Creating Literature -> Material relationships")
    print("=" * 70)

    driver = GraphDatabase.driver(URI, auth=(USERNAME, PASSWORD))

    with driver.session() as session:
        skip_count = 0
        ok_count = 0
        not_found = []

        for doi, materials, skip in PAPER_MATERIAL_MAP:
            # verify DOI exists
            result = session.run(
                "MATCH (p:Publication) WHERE p.doi = $d RETURN p.title AS title",
                d=doi
            )
            record = result.single()
            if not record:
                print(f"[NOT_FOUND] DOI: {doi}")
                not_found.append(doi)
                continue

            title = record["title"][:100]

            if skip:
                print(f"[SKIP] {doi} (review/2D perovskite)")
                print(f"       Title: {title}")
                skip_count += 1
                continue

            # create relationships
            for mat_raw in materials:
                mat_canon = get_canonical_name(mat_raw)

                # MERGE Material node
                session.run(
                    "MERGE (m:Material {name: $name}) SET m.category = 'Perovskite'",
                    name=mat_canon
                )

                # STUDIES relationship
                session.run("""
                    MATCH (p:Publication) WHERE p.doi = $d
                    MATCH (m:Material {name: $mname})
                    MERGE (p)-[:STUDIES]->(m)
                """, d=doi, mname=mat_canon)

                # HAS_EVIDENCE: try both naming conventions
                for pdf_name in [doi.replace('/', '_') + '.pdf', doi + '.pdf']:
                    session.run("""
                        MATCH (e:Evidence {source_pdf: $pdf})
                        MATCH (m:Material {name: $mname})
                        MERGE (m)-[:HAS_EVIDENCE]->(e)
                    """, pdf=pdf_name, mname=mat_canon)

                print(f"[OK] {doi} -> [{mat_canon}]  STUDIES + HAS_EVIDENCE")
                print(f"     Title: {title}")

            ok_count += 1

        # ========== Summary ==========
        print()
        print("=" * 70)
        print("[Summary]")
        print("=" * 70)
        print(f"  Created relationships: {ok_count} papers")
        print(f"  Skipped (reviews etc): {skip_count} papers")
        print(f"  DOI not in DB: {len(not_found)} papers")
        if not_found:
            for d in not_found:
                print(f"    - {d}")

        # verify
        result = session.run("""
            MATCH (pub:Publication)
            OPTIONAL MATCH (pub)-[:STUDIES]->(m:Material)
            WITH pub, CASE WHEN m IS NULL THEN 'no' ELSE 'has' END AS status
            RETURN status, count(DISTINCT pub) AS cnt
        """)
        for r in result:
            label = "WITH material" if r['status'] == 'has' else "WITHOUT material"
            print(f"  Publication {label}: {r['cnt']}")

        result = session.run("MATCH ()-[r:STUDIES]->() RETURN count(r) AS total")
        print(f"  Total STUDIES relationships: {result.single()['total']}")

    driver.close()
    print("\n[Done]")


if __name__ == "__main__":
    main()
