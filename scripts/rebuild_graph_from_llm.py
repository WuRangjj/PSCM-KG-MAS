# -*- coding: utf-8 -*-
"""
从 LLM 抽取结果重建知识图谱（取代正则可拉管路的 build_graph.py）

数据源：data/parsed/papers_with_relations.normalized.json
        （材料名已按 A 阶段映射表归一，类别词已剔除）

与旧 build_graph.py 的区别：
  * 旧版对 TI+AB 跑正则抽材料/性能/方法 -> 产生大量碎片节点和 "PCE=18.28" 拼接串
  * 新版只读 LLM 已抽取的结构化结果，材料名已归一，property 用 name/value/unit 三字段
  * 所有写入用 MERGE，可重复执行

用法：
    python rebuild_graph_from_llm.py --dry-run     # 只统计将要写入的内容
    python rebuild_graph_from_llm.py --apply
    python rebuild_graph_from_llm.py --apply --wipe   # 先清空旧图（危险，需备份）
"""
import sys, os, json, argparse
from collections import Counter
from neo4j import GraphDatabase

sys.stdout.reconfigure(encoding="utf-8")
P = r"C:\Users\20155\dpa4_project\data\parsed"
SRC = os.path.join(P, "papers_with_relations.normalized.json")
if not os.path.exists(SRC):
    SRC = os.path.join(P, "papers_with_relations.json")
URI, AUTH = "bolt://localhost:7687", ("neo4j", "wr20021218")

# 类别词/泛化词黑名单：这些不是具体材料，绝不建成 Material 节点
CATEGORY_BLACKLIST = set()
_cfgpath = r"C:\Users\20155\Documents\wr-deepseekharness\03-修复方案\A阶段-材料归并映射v3-最终.json"
if os.path.exists(_cfgpath):
    _cfg = json.load(open(_cfgpath, encoding="utf-8"))
    CATEGORY_BLACKLIST = {c["name"].strip().lower() for c in _cfg["category_terms"]}
    MERGE_MAP = _cfg["merge_map"]
else:
    MERGE_MAP = {}


def clean_material(name):
    """归一 + 黑名单过滤；返回 None 表示应丢弃"""
    if not isinstance(name, str) or not name.strip():
        return None
    n = MERGE_MAP.get(name, name).strip()
    if n.lower() in CATEGORY_BLACKLIST:
        return None
    return n

ap = argparse.ArgumentParser()
ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--apply", action="store_true")
ap.add_argument("--wipe", action="store_true")
args = ap.parse_args()
if not (args.dry_run or args.apply):
    ap.error("必须指定 --dry-run 或 --apply")

papers = json.load(open(SRC, encoding="utf-8"))["papers"]
print(f"数据源: {SRC}")
print(f"文献数: {len(papers)}")

# 预统计
mat_c, prop_c, meth_c, app_c = Counter(), Counter(), Counter(), Counter()
n_rel = Counter()
for p in papers:
    er = p.get("extracted_relations") or {}
    if not isinstance(er, dict):
        continue
    mats = set()
    cm = clean_material(er.get("main_material"))
    if cm:
        mats.add(cm)
    for key in ("materials", "dopants"):
        for m in er.get(key) or []:
            c = clean_material(m)
            if c:
                mats.add(c)
    for m in mats:
        mat_c[m] += 1
    for pr in er.get("properties") or []:
        if isinstance(pr, dict) and pr.get("name"):
            prop_c[str(pr["name"]).strip()] += 1
    for me in er.get("methods") or []:
        if isinstance(me, str) and me:
            meth_c[me] += 1
    for a in er.get("applications") or []:
        if isinstance(a, str) and a:
            app_c[a] += 1
    n_rel["STUDIES"] += len(mats)
    n_rel["CHARACTERIZED_BY"] += len(mats) * len(set(er.get("methods") or []))
    n_rel["USED_IN"] += len(mats) * len(set(er.get("applications") or []))
    n_rel["DOPED_WITH"] += len(mats) * len(set(er.get("dopants") or []))
    n_rel["RELATED_TO"] += len(mats) * len(set(er.get("related_materials") or []))

print(f"\n将写入（去重后）:")
print(f"  Publication : {len(papers)}")
print(f"  Material    : {len(mat_c)}")
print(f"  Property    : {len(prop_c)}   （键名种类: {len(prop_c)}）")
print(f"  Method      : {len(meth_c)}")
print(f"  Application : {len(app_c)}")
print(f"  关系上限    : {dict(n_rel)}")
print(f"\n高频材料 top10: {mat_c.most_common(10)}")
print(f"高频性能 top10: {prop_c.most_common(10)}")

if not args.apply:
    print("\n(dry-run，未写库)")
    sys.exit(0)

driver = GraphDatabase.driver(URI, auth=AUTH)
with driver.session() as s:
    if args.wipe:
        print("\n[WIPE] 清空既有图谱 ...")
        s.run("MATCH (n) DETACH DELETE n").consume()

    stats = Counter()
    for i, p in enumerate(papers, 1):
        doi = (p.get("DO") or f"unknown_{i}").strip()
        s.run("MERGE (pub:Publication {doi:$doi}) "
              "SET pub.title=$t, pub.journal=$j, pub.year=$y, "
              "    pub.times_cited=$c, pub.authors=$a",
              doi=doi, t=p.get("TI", ""), j=p.get("T2", ""), y=p.get("PY", ""),
              c=p.get("TIMES_CITED", 0), a=p.get("AU", []) or []).consume()
        stats["Publication"] += 1

        er = p.get("extracted_relations") or {}
        if not isinstance(er, dict):
            continue

        mats = set()
        cm = clean_material(er.get("main_material"))
        if cm:
            mats.add(cm)
        for key in ("materials", "dopants"):
            for m in er.get(key) or []:
                c = clean_material(m)
                if c:
                    mats.add(c)

        for m in mats:
            s.run("MERGE (m:Material {name:$n}) SET m.category='Perovskite'", n=m).consume()
            s.run("MATCH (pub:Publication {doi:$doi}) MATCH (m:Material {name:$n}) "
                  "MERGE (pub)-[:STUDIES]->(m)", doi=doi, n=m).consume()
            stats["Material"] += 1

        # 性能：与 D 阶段一致的结构
        #   (m:Material)-[:HAS_PROPERTY {value:[...], unit, value_max, n_values,...}]->(p:Property {name})
        #   每种性能只建一个节点，不再拼 "PCE=18.28"
        for pr in er.get("properties") or []:
            if not (isinstance(pr, dict) and pr.get("name")):
                continue
            name = str(pr["name"]).strip()
            if not name:
                continue
            raw_v = str(pr.get("value", "") or "")
            try:
                val = float(raw_v.replace("%", "").replace(",", "").strip())
            except Exception:
                continue
            unit = str(pr.get("unit", "") or "").strip() or None
            s.run("MERGE (p:Property {name:$n}) SET p.canonical = true", n=name).consume()
            for m in mats:
                s.run("MATCH (m:Material {name:$mat}) MATCH (p:Property {name:$n}) "
                      "MERGE (m)-[r:HAS_PROPERTY]->(p) "
                      "SET r.value = coalesce(r.value, []) + $v, "
                      "    r.value_raw = coalesce(r.value_raw, []) + $raw, "
                      "    r.unit = coalesce(r.unit, $u), "
                      "    r.value_max = CASE WHEN r.value_max IS NULL OR r.value_max < $v "
                      "                       THEN $v ELSE r.value_max END, "
                      "    r.value_min = CASE WHEN r.value_min IS NULL OR r.value_min > $v "
                      "                       THEN $v ELSE r.value_min END, "
                      "    r.n_values = size(coalesce(r.value, []) + $v), "
                      "    r.n_numeric = size(coalesce(r.value, []) + $v), "
                      "    r._patch_batch = 'rebuild-from-llm'",
                      mat=m, n=name, v=[val], raw=[raw_v], u=unit).consume()
            stats["Property"] += 1

        for me in set(er.get("methods") or []):
            if not isinstance(me, str) or not me:
                continue
            s.run("MERGE (x:Method {name:$n})", n=me).consume()
            for m in mats:
                s.run("MATCH (m:Material {name:$mat}) MATCH (x:Method {name:$n}) "
                      "MERGE (m)-[:CHARACTERIZED_BY]->(x)", mat=m, n=me).consume()
            stats["Method"] += 1

        for a in set(er.get("applications") or []):
            if not isinstance(a, str) or not a:
                continue
            s.run("MERGE (x:Application {name:$n})", n=a).consume()
            for m in mats:
                s.run("MATCH (m:Material {name:$mat}) MATCH (x:Application {name:$n}) "
                      "MERGE (m)-[:USED_IN]->(x)", mat=m, n=a).consume()
            stats["Application"] += 1

        for d in set(er.get("dopants") or []):
            if not isinstance(d, str) or not d:
                continue
            for m in mats:
                s.run("MATCH (m:Material {name:$mat}) MATCH (d:Material {name:$dn}) "
                      "MERGE (m)-[:DOPED_WITH]->(d)", mat=m, dn=d).consume()

        for rm in set(er.get("related_materials") or []):
            if not isinstance(rm, str) or not rm:
                continue
            for m in mats:
                s.run("MATCH (m:Material {name:$mat}) MATCH (r:Material {name:$rn}) "
                      "MERGE (m)-[:RELATED_TO]->(r)", mat=m, rn=rm).consume()

        if i % 100 == 0:
            print(f"  {i}/{len(papers)}")

    print(f"\n完成。MERGE 次数统计: {dict(stats)}")
    for lab in ["Publication", "Material", "Property", "Method", "Application"]:
        c = s.run(f"MATCH (n:{lab}) RETURN count(n) AS c").single()["c"]
        print(f"  {lab}: {c}")

driver.close()
print("\n注意：Evidence 节点不在本脚本范围内，由 extract_*_full.py 生成，")
print("      关联请跑 B_fix_evidence.py。")
