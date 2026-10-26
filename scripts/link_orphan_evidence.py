# -*- coding: utf-8 -*-
"""
Link orphaned J-V Evidence to Material nodes.
Step 1: Auto-link those whose Publication already has STUDIES -> Material
Step 2: Report those needing manual judgment
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
from neo4j import GraphDatabase

URI = "bolt://localhost:7687"
USERNAME = "neo4j"
PASSWORD = "wr20021218"


def main():
    driver = GraphDatabase.driver(URI, auth=(USERNAME, PASSWORD))

    with driver.session() as session:
        # Find all orphaned J-V Evidence (not linked to any Material)
        raw = session.run("""
            MATCH (e:Evidence)
            WHERE e.image_type = 'J-V曲线'
              AND NOT (e)<-[:HAS_EVIDENCE]-(:Material)
            RETURN e.source_pdf AS pdf
            ORDER BY pdf
        """)
        orphans = [r["pdf"] for r in raw]
        print(f"Orphaned J-V Evidence: {len(orphans)}")
        print()

        auto_links = []
        manual_list = []
        no_pub_list = []

        for pdf in orphans:
            # Convert source_pdf to DOI
            doi = pdf
            if doi.endswith('.pdf'):
                doi = doi[:-4]
            doi = doi.replace('_', '/')

            # Find Publication
            rec = session.run(
                "MATCH (p:Publication) WHERE p.doi = $d RETURN p.title AS title, p.doi AS pdoi",
                d=doi
            ).single()

            if not rec:
                no_pub_list.append((pdf, doi))
                continue

            title = rec["title"]

            # Check if Publication already has Materials
            mats_rec = session.run("""
                MATCH (p:Publication) WHERE p.doi = $d
                MATCH (p)-[:STUDIES]->(m:Material)
                RETURN collect(DISTINCT m.name) AS materials
            """, d=doi).single()

            if mats_rec and mats_rec["materials"]:
                auto_links.append((pdf, doi, title, mats_rec["materials"]))
            else:
                manual_list.append((pdf, doi, title))

        # ====== Report ======
        print(f"Auto-linkable (Pub has Material): {len(auto_links)}")
        print(f"Need manual judgment:              {len(manual_list)}")
        print(f"No matching Publication:           {len(no_pub_list)}")
        print()

        # Auto-link
        if auto_links:
            print("=" * 60)
            print("[AUTO-LINKING]")
            print("=" * 60)
            ok = 0
            for pdf, doi, title, materials in auto_links:
                for mat in materials:
                    session.run("""
                        MATCH (m:Material {name: $mname})
                        MATCH (e:Evidence) WHERE e.source_pdf = $sp
                        MERGE (m)-[:HAS_EVIDENCE]->(e)
                    """, mname=mat, sp=pdf)
                print(f"  [OK] {doi} -> {materials}")
                print(f"       {title[:100]}")
                ok += 1
            print(f"\nAuto-linked: {ok} papers")

        # Manual list
        if manual_list:
            print()
            print("=" * 60)
            print("[NEED MANUAL JUDGMENT]")
            print("=" * 60)
            for i, (pdf, doi, title) in enumerate(manual_list, 1):
                print(f"{i:2d}. {doi}")
                print(f"    {title[:120]}")

        # Verify
        print()
        print("=" * 60)
        print("[VERIFY]")
        result = session.run("""
            MATCH (m:Material)-[:HAS_EVIDENCE]->(e:Evidence)
            WHERE e.image_type = 'J-V曲线'
            RETURN count(e) AS paths, count(DISTINCT e) AS distinct_ev
        """).single()
        print(f"Material->J-V paths: {result['paths']}")
        print(f"Distinct J-V Evidence linked: {result['distinct_ev']}")

        result = session.run("MATCH (e:Evidence) WHERE e.image_type = 'J-V曲线' RETURN count(e) AS cnt").single()
        print(f"Total J-V Evidence: {result['cnt']}")

    driver.close()
    print("\n[Done]")


if __name__ == "__main__":
    main()
