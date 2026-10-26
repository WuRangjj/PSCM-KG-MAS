# -*- coding: utf-8 -*-
"""
Fix HAS_EVIDENCE links: Evidence source_pdf has multiple formats
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
from neo4j import GraphDatabase

URI = "bolt://localhost:7687"
USERNAME = "neo4j"
PASSWORD = "wr20021218"

TARGET_DOIS = [
    ("10.1126/science.aaa0472",     "MAPbI3"),
    ("10.1126/science.aai9081",     "MAPbI3"),
    ("10.1126/science.aai9081",     "FAPbI3"),
    ("10.1021/jacs.5b04930",        "MAPbI3"),
    ("10.1021/acs.chemmater.5b04107", "FAPbI3"),
    ("10.1021/acs.chemmater.5b04107", "CsPbI3"),
    ("10.1038/NNANO.2015.230",      "MAPbI3"),
    ("10.1016/j.joule.2019.06.014", "MAPbI3"),
    ("10.1038/ncomms8747",          "MAPbI3"),
    ("10.1021/jacs.5b01994",        "MAPbI3"),
    ("10.1038/s41467-019-08507-4",  "MAPbI3"),
    ("10.1038/s41467-019-08507-4",  "FAPbI3"),
    ("10.1021/acs.jpcc.6b01728",    "MAPbI3"),
    ("10.1021/acs.chemmater.5b01991", "MAPbI3"),
    ("10.1039/c6ta08783c",          "MAPbI3"),
    ("10.1021/jp510837q",           "MAPbI3"),
    ("10.1021/acs.nanolett.6b03119", "MAPbI3"),
    ("10.1038/s41467-020-20749-1",  "CsPbI3"),
    ("10.1038/s41467-020-20749-1",  "FAPbI3"),
]


def main():
    driver = GraphDatabase.driver(URI, auth=(USERNAME, PASSWORD))

    with driver.session() as session:
        ok = 0
        fail = 0

        for doi, mat in TARGET_DOIS:
            # Try multiple source_pdf formats
            candidates = [
                doi.replace('/', '_') + '.pdf',
                doi,
                doi + '.pdf',
                doi.replace('/', '_'),
            ]

            matched_pdf = None
            for pdf_name in candidates:
                result = session.run(
                    "MATCH (e:Evidence) WHERE e.source_pdf = $sp RETURN e.source_pdf AS sp, e.image_type AS it",
                    sp=pdf_name
                )
                rec = result.single()
                if rec:
                    matched_pdf = rec["sp"]
                    break

            if not matched_pdf:
                print(f"[NO_EVIDENCE] {doi} (tried: {candidates})")
                fail += 1
                continue

            # Create HAS_EVIDENCE
            session.run("""
                MATCH (m:Material {name: $mname})
                MATCH (e:Evidence) WHERE e.source_pdf = $sp
                MERGE (m)-[:HAS_EVIDENCE]->(e)
            """, mname=mat, sp=matched_pdf)

            print(f"[OK] {mat} <-HAS_EVIDENCE- Evidence({matched_pdf})")
            ok += 1

        print()
        print(f"Created: {ok}, Failed: {fail}")

        # Verify
        result = session.run("""
            MATCH (m:Material)-[:HAS_EVIDENCE]->(e:Evidence)
            WHERE e.image_type = 'J-V曲线'
            RETURN count(DISTINCT e) AS cnt
        """)
        print(f"Total Evidence linked to Material (J-V): {result.single()['cnt']}")

        result = session.run("""
            MATCH (e:Evidence)
            WHERE e.image_type = 'J-V曲线'
            RETURN count(e) AS cnt
        """)
        print(f"Total J-V Evidence in DB: {result.single()['cnt']}")

    driver.close()
    print("[Done]")


if __name__ == "__main__":
    main()
