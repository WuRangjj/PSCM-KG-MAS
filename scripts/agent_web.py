import json
import re
import streamlit as st
from neo4j import GraphDatabase
from openai import OpenAI
from dotenv import load_dotenv
import os
from datetime import datetime

load_dotenv()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "wr20021218"

# 所有 LLM 调用的输出上限。必须显式设置：
# DeepSeek 系列模型会先输出推理内容，预算不足时正文会被截断成空字符串。
LLM_MAX_TOKENS = 3000

# 类别词/器件层名称：这些不是具体材料，不能被当成查询目标
_CATEGORY_CFG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..", "wr-deepseekharness", "03-修复方案", "A阶段-材料归并映射v3-最终.json")


def load_category_terms():
    """读取类别词黑名单；文件缺失时退回内置最小集合"""
    fallback = {"perovskite", "perovskites", "halide perovskite",
                "metal halide perovskite", "lead halide perovskite",
                "perovskite solar cell", "absorber", "film"}
    for p in (_CATEGORY_CFG,
              r"C:\Users\20155\Documents\wr-deepseekharness\03-修复方案"
              r"\A阶段-材料归并映射v3-最终.json"):
        try:
            cfg = json.load(open(p, encoding="utf-8"))
            return {c["name"].strip().lower() for c in cfg.get("category_terms", [])} | fallback
        except Exception:
            continue
    return fallback


CATEGORY_TERMS = load_category_terms()

st.set_page_config(page_title="Perovskite Multi-Agent System", page_icon="🧠", layout="wide")
st.title("🧠 Perovskite Materials Multi-Agent Analysis System")
st.markdown("**Planner → KG-Miner → Scientist → Critic → Editor** working collaboratively")
st.markdown("---")


@st.cache_resource
def init_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


@st.cache_resource
def init_llm():
    return OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")


driver = init_driver()
llm_client = init_llm()


# material_search 的停用词：从问句里抠检索关键词时排除
_KW_STOP = re.compile(
    r"(相关的材料有哪些|相关的材料有那些|相关材料|有哪些材料|有哪些|材料有哪些|"
    r"相关的|有关的|之类|等等|请问|帮我|我想知道|是什么|有哪些呢|"
    r"相关的有|包含|含有|涉及|related|materials?|which|what|about)", re.I)
# 化学式候选：从大写字母开始、由「字母+数字」片段连续组成的 token
#   C60 → C60   Sn → Sn   CsPbI3 → CsPbI3   MAPbI3 → MAPbI3   FAPb(I0.85Br0.15)3 → FAPb
#   关键：(?:\d*[A-Za-z]+\d*)* 让「元素符号+数字」可以一直连下去，不会在 CsPbI3 的 b 处断开
_KW_FORMULA = re.compile(r"[A-Z][a-z]*\d*(?:\d*[A-Za-z]+\d*)*")


def _extract_keyword(query):
    """从问句里抠出用于图谱检索的关键词。
    例：'C60 相关的材料有哪些？' → 'C60'
        '含 Sn 的钙钛矿有哪些'   → 'Sn'
        'CsPbI3 相关的材料'      → 'CsPbI3'
    """
    q = re.sub(r"[？?！!。，,、；;：:\s]+", " ", str(query or "")).strip()
    skip = {"The", "And", "For", "With", "Are", "What", "Which", "How",
            "Is", "Of", "In", "On", "A", "An", "I"}
    cands = []
    for m in _KW_FORMULA.finditer(q):
        t = m.group(0)
        if t in skip or len(t) < 2:
            continue
        cands.append(t)
    if not cands:
        # 退化为：去掉停用词后最长的中文/英文片段
        s = _KW_STOP.sub(" ", q)
        parts = [p.strip() for p in re.split(r"\s+", s) if len(p.strip()) >= 2]
        return max(parts, key=len) if parts else ""
    # 优先带数字的（更像化学式），其次最长的
    with_digit = [c for c in cands if any(ch.isdigit() for ch in c)]
    if with_digit:
        return max(with_digit, key=len)
    return max(cands, key=len)


def _is_category(kw):
    """关键词是否是类别词（泛称），不适合直接做图谱检索"""
    k = str(kw or "").strip().lower()
    if not k:
        return False
    if k in CATEGORY_TERMS:
        return True
    return bool(re.search(r"perovskite|钙钛矿|halide|absorber|absorbing", k))


class Planner:
    def __init__(self, llm_client):
        self.llm = llm_client

    def plan(self, user_query):
        prompt = f"""你是钙钛矿材料领域的任务规划专家。

Answer in English. All output text (answer, evidence_used, limitations, reason) must be written in English.
用户提出了一个问题，你需要判断问题类型并给出执行计划。

用户问题：{user_query}

问题类型：
1. material_query：关于【某个具体材料】的任何问题，包括
   · 它的性能、方法、掺杂
   · "哪些文献研究了它"、"出处是什么"、"DOI 是什么"、"有哪些证据"
   （问题里出现一个明确的材料名，就归这一类）
2. material_compare：比较两种或多种材料
3. material_search：用户想找【一批符合条件的材料】，条件是材料名称或元素组成
   （如"C60 相关的材料"、"含 Sn 的钙钛矿"）
   注意：如果问题里已经点明了具体材料名，不要用这一类
4. property_filter：按性能的【数值范围】筛选材料
   （如"带隙在 1.2-1.3 eV 之间的材料"、"PCE 超过 25% 的材料"、"Voc 低于 1.0 V 的材料"）
   注意：这类问题问的是**性能数值**，不是材料名称，绝对不要把性能名当 search_keyword
5. corpus_statistics：问图谱的统计量
   （如"图谱里有多少个材料节点"、"多少篇文献"、"多少材料报道了 PCE"、"有多少方法"）
6. general：其他问题（包括图谱覆盖范围之外的问题）

要求（重要）：
- materials 字段必须填**具体的材料化学式**，例如 MAPbI3、FAPbI3、CsPbI3、Spiro-OMeTAD
- **不要**把泛称当成材料名：perovskite、halide perovskite、metal halide perovskite、
  perovskite solar cell、absorber 等都不是具体材料，出现这类说法时 materials 留空数组
- 如果用户问的是某一类材料（如"钙钛矿材料的效率"），把 task_type 设为 material_search、
  materials 留空，并在 intent 里说明范围
- 材料名用学术界通用短式（MAPbI3 而非 CH3NH3PbI3）
- **绝对不要改变材料的化学组成**：CH3NH3GeI3 是锗基材料（即 MAGeI3），
  **不能**写成 MAPbI3（铅基）；MA 与 FA、Sn 与 Pb、Ge 与 Pb 都不可互换。
  如果拿不准通用短式，**原样保留提问里出现的化学式**，不要自己改写
- 如果提问里的化学式看起来不完整（如 APbI），也原样保留，不要补全成别的材料

输出 JSON：
{{
    "task_type": "material_query" 或 "material_compare" 或 "material_search"
                 或 "property_filter" 或 "corpus_statistics" 或 "general",
    "materials": ["具体材料的化学式列表，没有则为空数组"],
    "search_keyword": "material_search 时要在图谱里检索的关键词（如 C60、Sn、Br、2D）；
                       其他类型填空字符串",
    "property_name": "property_filter 时的性能名，必须从图谱实际存在的
                      性能里选（区分大小写，原样填写）：
                      PCE / PCE_certified / Voc / Jsc / FF / Bandgap /
                      Mobility / Stability / EQE / PLQY / CarrierLifetime /
                      DiffusionLength / TrapDensity / VocDeficit / ASEThreshold；
                      注意不要把「载流子寿命」写成 Stability，也不要
                      把「陷阱密度」写成别的；其他类型填空字符串",
    "property_min": "property_filter 时的数值下限（纯数字，没有则 null）",
    "property_max": "property_filter 时的数值上限（纯数字，没有则 null）",
    "stat_kind": "corpus_statistics 时的统计对象，必须从下面选（原样填写）：
                  节点类：material / publication / method / application /
                          evidence / property
                  关系总数：relation
                  具体关系类型：has_property / characterized_by / studies /
                          has_evidence / related_to / used_in / doped_with /
                          from_publication
                  材料覆盖：material_studied / material_without_study /
                          material_with_pce / material_with_bandgap
                  排行榜类（问「哪几个最多/最高」）：top_materials /
                          top_properties / top_methods；
                  问「有多少条 XX 关系」填对应关系类型名
                  （如 HAS_PROPERTY -> has_property），不要一律填 relation；
                  问「哪几个材料被研究最多」填 top_materials，
                  不要填 material_studied",
    "intent": "用户想做什么（一句话）",
    "sub_tasks": ["子任务1", "子任务2"]
}}
"""
        try:
            response = self.llm.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are a task-planning expert. Output JSON only, in English."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=LLM_MAX_TOKENS,
                response_format={"type": "json_object"}
            )
            plan = json.loads(response.choices[0].message.content)
            # 后置防线：LLM 仍可能把类别词当材料，这里强制剔除
            raw = plan.get("materials") or []
            kept = [m for m in raw if str(m).strip().lower() not in CATEGORY_TERMS]
            dropped = [m for m in raw if m not in kept]
            if dropped:
                plan["_dropped_category_terms"] = dropped
            plan["materials"] = kept

            # 第二道防线：用图谱 _scope 标记剔除「描述性垃圾材料」
            # （如 'C60 electron transport layer'、'carrier transport layers'）
            # 只做提示，不阻断——这些节点在库里确实存在
            junk = []
            if kept:
                with driver.session() as _s:
                    for m in list(kept):
                        # 用 size(pattern comprehension) 判断是否被研究过，
                        # 不能直接 RETURN 模式表达式（Neo4j 语法不允许）
                        r = _s.run("MATCH (x:Material {name:$n}) "
                                   "RETURN x._scope AS sc, "
                                   "size([(x)<-[:STUDIES]-() | 1]) AS n_studied",
                                   n=m).single()
                        if r and r["sc"] in ("generic",) and not r["n_studied"]:
                            junk.append(m)
            if junk:
                plan["_junk_materials"] = junk

            if dropped and not kept and plan.get("task_type") == "material_query":
                plan["task_type"] = "material_search"

            # 兜底：material_search 但 LLM 没给关键词 → 直接从问句里抠
            if plan.get("task_type") == "material_search":
                kw = str(plan.get("search_keyword") or "").strip()
                fallback_used = False
                if not kw or _is_category(kw):
                    ek = _extract_keyword(user_query)
                    if ek and not _is_category(ek):
                        kw = ek
                        fallback_used = True
                    elif _is_category(kw or ek):
                        kw = ""      # 只有类别词 → 交给上层走「请指明具体材料」分支
                if fallback_used:
                    plan["_keyword_fallback"] = kw
                plan["search_keyword"] = kw
            return plan
        except Exception as e:
            return {"task_type": "general", "materials": [],
                    "intent": f"解析失败: {str(e)}", "sub_tasks": []}



def fmt_num(v, unit):
    """把基准单位的值转成人读友好的单位（0.0000182 s -> 18.2 μs）"""
    if v is None:
        return "—"
    if unit == "s":
        if v < 1e-6:
            return f"{v*1e9:.1f} ns"
        if v < 1e-3:
            return f"{v*1e6:.2f} μs"
        if v < 1:
            return f"{v*1e3:.2f} ms"
        return f"{v:.1f} s"
    if unit == "m":
        if v < 1e-6:
            return f"{v*1e9:.1f} nm"
        if v < 1e-3:
            return f"{v*1e6:.2f} μm"
        if v < 1:
            return f"{v*1e3:.2f} mm"
        return f"{v:.3f} m"
    if isinstance(v, float) and v == int(v):
        return f"{int(v)}{unit}"
    return f"{v}{unit}"


class KG_Miner:
    def __init__(self, driver):
        self.driver = driver

    def get_material_properties(self, material_name, top=25):
        """
        D 阶段后的新 schema：
          (m:Material)-[:HAS_PROPERTY {value:[...], unit, value_max, value_avg,
                                       n_values, n_numeric}]->(p:Property {name})
        返回可直接读的字符串，附带数值数量，便于 Scientist 引用。
        """
        with self.driver.session() as session:
            result = session.run(
                "MATCH (m:Material {name: $name})-[r:HAS_PROPERTY]->(p:Property) "
                "RETURN p.name AS property, r.value_max AS vmax, r.value_min AS vmin, "
                "       r.value_avg AS vavg, r.unit AS unit, r.unit_max AS umax, "
                "       r.unit_min AS umin, r.n_numeric AS nnum, "
                "       r.n_values AS nval, r.value_text AS vtext, "
                "       r.value_suspect AS vsus, r.value_time AS vtime, "
                "       r.time_unit AS tunit "
                "ORDER BY r.n_numeric DESC, p.name",
                name=material_name
            )
            out = []
            for rec in result:
                prop = rec["property"]
                umax = rec["umax"] or rec["unit"]
                umin = rec["umin"] or rec["unit"]
                parts = []
                if rec["vmax"] is not None:
                    parts.append(f"最高 {fmt_num(rec['vmax'], umax)}")
                if rec["vavg"] is not None and (rec["nnum"] or 0) > 1:
                    parts.append(f"均值 {fmt_num(rec['vavg'], rec['unit'])}")
                if rec["vmin"] is not None and (rec["nnum"] or 0) > 1:
                    parts.append(f"最低 {fmt_num(rec['vmin'], umin)}")
                if rec["vtime"]:
                    parts.append(f"时长数据 最长 {fmt_num(max(rec['vtime']), rec['tunit'] or '')}"
                                 f"（{len(rec['vtime'])} 条，非保持率）")
                if rec["vtext"]:
                    parts.append("另有描述: " + "; ".join(rec["vtext"][:3]))
                if rec["vsus"]:
                    parts.append(f"（{len(rec['vsus'])} 个越界值已隔离: {rec['vsus'][:3]}）")
                n = rec["nnum"] or 0
                if parts:
                    out.append(f"{prop}: {', '.join(parts)} [数值 {n} 条]")
                else:
                    out.append(f"{prop}: {', '.join(rec['vtext'] or []) or '无数值'}")
            return out[:top]

    def get_material_properties_numeric(self, material_name):
        """只要数值，供对比功能做程序化判断，不依赖 LLM 读字符串"""
        with self.driver.session() as session:
            result = session.run(
                "MATCH (m:Material {name: $name})-[r:HAS_PROPERTY]->(p:Property) "
                "WHERE r.value_max IS NOT NULL "
                "RETURN p.name AS property, r.value_max AS vmax, r.value_avg AS vavg, "
                "       r.unit AS unit, r.n_numeric AS n",
                name=material_name
            )
            return {rec["property"]: {"max": rec["vmax"], "avg": rec["vavg"],
                                      "unit": rec["unit"], "n": rec["n"]}
                    for rec in result}


    def get_material_methods(self, material_name):
        with self.driver.session() as session:
            result = session.run(
                "MATCH (m:Material {name: $name})-[:CHARACTERIZED_BY]->(met:Method) "
                "RETURN met.name AS method",
                name=material_name
            )
            return [record["method"] for record in result]

    def get_material_methods_ranked(self, material_name):
        """方法按『被多少材料共用』降序返回 [(名称, 共用材料数)]，
        这样通用工艺（spin-coating 等）排前面，而不是被字母序/插入序打乱"""
        with self.driver.session() as session:
            result = session.run(
                "MATCH (m:Material {name: $name})-[:CHARACTERIZED_BY]->(met:Method) "
                "RETURN met.name AS method, count { (met)<-[:CHARACTERIZED_BY]-() } AS shared "
                "ORDER BY shared DESC, met.name",
                name=material_name
            )
            return [(r["method"], r["shared"]) for r in result]


    def get_material_applications(self, material_name):
        with self.driver.session() as session:
            result = session.run(
                "MATCH (m:Material {name: $name})-[:USED_IN]->(a:Application) "
                "RETURN a.name AS application",
                name=material_name
            )
            return [record["application"] for record in result]

    def get_dopants(self, material_name):
        with self.driver.session() as session:
            result = session.run(
                "MATCH (m:Material {name: $name})-[:DOPED_WITH]->(d:Material) "
                "RETURN d.name AS dopant",
                name=material_name
            )
            return [record["dopant"] for record in result]

    def get_material_evidence(self, material_name):
        with self.driver.session() as session:
            result = session.run(
                "MATCH (m:Material {name: $name})-[:HAS_EVIDENCE]->(e:Evidence) "
                "RETURN e.image_type, e.extracted_data, e.figures, e.page",
                name=material_name
            )
            return [{"image_type": record["e.image_type"],
                     "extracted_data": record["e.extracted_data"],
                     "figures": record["e.figures"],
                     "page": record["e.page"]} for record in result]

    @staticmethod
    def _evidence_lines(evidence, top=12):
        """把 Evidence 转成给 LLM 看的证据行。
        兼容两代 schema：
          旧（v2）：extracted_data 是平铺字典，含 PCE/Voc/Jsc/FF 或 peaks/morphology
          新（v3）：extracted_data={"figures":[...]}，每个 figure 带 kind/values/material
        """
        lines = []

        def num(v):
            if v is None or v == "":
                return None
            if isinstance(v, (int, float)):
                return v
            try:
                return float(str(v).replace("%", "").strip())
            except Exception:
                return None

        def fmt_vals(v, mats=None, tag=""):
            if not isinstance(v, dict):
                return None
            pce = num(v.get("PCE"))
            voc = num(v.get("Voc"))
            jsc = num(v.get("Jsc"))
            ff = num(v.get("FF"))
            if None in (pce, voc, jsc, ff):
                return None
            m = f" 材料={mats}" if mats else ""
            return (f"[J-V证据{tag}] PCE={pce}% Voc={voc}V "
                    f"Jsc={jsc}mA/cm² FF={ff}%{m}")

        for e in (evidence or []):
            # --- 新 schema ---
            figs = None
            if e.get("figures"):
                try:
                    figs = json.loads(e["figures"]) if isinstance(e["figures"], str) \
                        else e["figures"]
                except Exception:
                    figs = None
            if not figs and e.get("extracted_data"):
                try:
                    d0 = json.loads(e["extracted_data"]) \
                        if isinstance(e["extracted_data"], str) else e["extracted_data"]
                    if isinstance(d0, dict) and isinstance(d0.get("figures"), list):
                        figs = d0["figures"]
                except Exception:
                    figs = None

            if figs:
                pg = f" p{e['page']}" if e.get("page") else ""
                for f in figs:
                    kind = str(f.get("kind") or "")
                    mat = f.get("material")
                    vals = f.get("values") or {}
                    txt = (f.get("text_content") or "")[:70]
                    line = None
                    if kind in ("J-V curve", "J-V曲线") or all(
                            vals.get(k) is not None
                            for k in ("PCE", "Voc", "Jsc", "FF")):
                        line = fmt_vals(vals, mat, pg)
                    if line:
                        lines.append(line)
                    elif "XRD" in kind:
                        lines.append(f"[XRD证据{pg}] 2θ={vals.get('peak_2theta')} "
                                     f"材料={mat}")
                    elif kind in ("SEM", "TEM", "AFM"):
                        lines.append(f"[{kind}证据{pg}] 材料={mat} {txt}")
                    elif kind in ("table", "表格"):
                        # 表格常只给 PCE 一列，不能因 J-V 四项不全就丢弃
                        pce = num(vals.get("PCE"))
                        extra = f" PCE={pce}%" if pce is not None else ""
                        lines.append(f"[表格证据{pg}] 材料={mat}{extra} {txt}")
                    if len(lines) >= top:
                        return lines
                continue

            # --- 旧 schema ---
            try:
                d = json.loads(e.get("extracted_data") or "{}") \
                    if isinstance(e.get("extracted_data"), str) else (e.get("extracted_data") or {})
            except Exception:
                d = {}
            if not isinstance(d, dict):
                continue
            t = d.get("type") or e.get("image_type")
            if t and str(t).startswith("J-V"):
                line = fmt_vals(d)
                if line:
                    lines.append(line)
            elif t == "XRD":
                lines.append(f"[XRD证据] 主相={d.get('dominant_phase')} "
                             f"峰数={len(d.get('peaks') or [])}")
            elif t == "SEM":
                lines.append(f"[SEM证据] 形貌={(d.get('morphology') or '')[:80]}")
            elif t == "表格":
                hdr = d.get("headers") or []
                lines.append(f"[表格证据] 列={hdr[:6]} 行数={len(d.get('rows') or [])}")
            if len(lines) >= top:
                break
        return lines

    @staticmethod
    def _figs_of(e):
        """取某条证据的 figures 列表。figures 可能是 JSON 字符串，
        也可能嵌在 extracted_data 里，必须两种都兼容。"""
        figs = None
        if e.get("figures"):
            try:
                figs = (json.loads(e["figures"])
                        if isinstance(e["figures"], str) else e["figures"])
            except Exception:
                figs = None
        if not figs and e.get("extracted_data"):
            try:
                d0 = (json.loads(e["extracted_data"])
                      if isinstance(e["extracted_data"], str)
                      else e["extracted_data"])
                if isinstance(d0, dict) and isinstance(d0.get("figures"), list):
                    figs = d0["figures"]
            except Exception:
                figs = None
        return figs if isinstance(figs, list) else []

    @staticmethod
    def _evidence_summary(evidence, top=12):
        """按【页码】汇总证据，每页一行。
        必须用它来做覆盖面统计——_evidence_lines 是按 figure 顺序取的，
        若某页 figure 特别多（如 6874 条），会把 top 配额吃光，
        导致其它页面的证据完全看不到。"""
        from collections import defaultdict
        agg = defaultdict(lambda: {"types": set(), "figs": 0, "vals": []})
        for e in evidence:
            pg = e.get("page")
            a = agg[pg]
            for k in str(e.get("image_type") or "").split("|"):
                if k.strip():
                    a["types"].add(k.strip())
            figs = KG_Miner._figs_of(e)
            a["figs"] += len(figs)
            if len(a["vals"]) < 3:
                for f in figs:
                    if not isinstance(f, dict):
                        continue
                    vals = f.get("values")
                    if not isinstance(vals, dict):
                        continue
                    pce = vals.get("PCE")
                    if pce is not None:
                        mat = f.get("material") or "?"
                        a["vals"].append(f"{mat} PCE={pce}%")
                        if len(a["vals"]) >= 3:
                            break
        out = []
        for pg in sorted(agg, key=lambda x: (x is None, x or 0)):
            a = agg[pg]
            t = ", ".join(sorted(a["types"])[:7])
            s = (f"page {pg}: {t}" if pg is not None else f"page ?: {t}")
            s += f"  [{a['figs']} figure entries]"
            if a["vals"]:
                s += "  e.g. " + "; ".join(a["vals"][:2])
            out.append(s)
            if len(out) >= top:
                break
        if len(agg) > top:
            out.append(f"…… 另有 {len(agg) - top} 页证据未列出")
        return out

    def search_materials(self, keyword):
        """按关键词搜材料。优先返回真正的钙钛矿吸收层材料，
        把 _scope 标为 non_absorber / generic / uncertain 的排在后面，
        避免检索到 'C60 electron transport layer' 这类描述性垃圾节点。"""
        with self.driver.session() as session:
            result = session.run(
                "MATCH (m:Material) WHERE m.name CONTAINS $keyword "
                "RETURN m.name AS name, m._scope AS scope LIMIT 30",
                keyword=keyword
            )
            rows = [(r["name"], r["scope"]) for r in result]
        order = {"perovskite": 0, "uncertain": 1, None: 1,
                 "non_absorber": 2, "generic": 3}
        rows.sort(key=lambda x: order.get(x[1], 1))
        return [n for n, _ in rows[:10]]

    # ---------------- 新增：文献溯源 ----------------
    def count_publications_for_material(self, material_name):
        """统计研究某材料的文献篇数（不受 top 限制）"""
        with self.driver.session() as session:
            r = session.run(
                "MATCH (p:Publication)-[:STUDIES]->(m:Material {name:$n}) "
                "RETURN count(DISTINCT p) AS c", n=material_name).single()
        return r["c"] if r else 0

    def get_material_publications(self, material_name, top=15):
        """返回研究该材料的文献：DOI | 期刊 | 年份 | 被引"""
        with self.driver.session() as session:
            rows = list(session.run(
                "MATCH (p:Publication)-[:STUDIES]->(m:Material {name:$n}) "
                "RETURN p.doi AS doi, p.journal AS j, p.year AS y, "
                "       p.times_cited AS tc "
                "ORDER BY p.year DESC, p.times_cited DESC LIMIT $t",
                n=material_name, t=top))
        out = []
        for r in rows:
            jn = (r["j"] or "").strip()
            if jn.isupper():
                jn = jn.title()
            bits = [r["doi"] or "(no DOI)"]
            if jn:
                bits.append(jn)
            if r["y"]:
                bits.append(str(r["y"]))
            if r["tc"]:
                bits.append(f"cited {r['tc']}")
            out.append(" | ".join(bits))
        return out

    # ---------------- 新增：按性能数值筛选 ----------------
    def _prop_where(self, prop_name, vmin, vmax):
        """精确口径：材料的【任一数值】落在 [vmin, vmax] 内才算命中。
        不要用 value_min/value_max 的区间重叠判断——那会把
        '带隙 1.0-2.0 eV' 这种宽区间材料也算进来。"""
        params = {"p": prop_name,
                  "vmin": float(vmin) if vmin is not None else -1e308,
                  "vmax": float(vmax) if vmax is not None else 1e308}
        return ("r.value IS NOT NULL AND "
                "any(v IN r.value WHERE v >= $vmin AND v <= $vmax)"), params

    def filter_by_property(self, prop_name, vmin=None, vmax=None, top=25):
        """按性能数值范围筛选材料，返回 (材料名, 命中数值列表, 单位)"""
        where, params = self._prop_where(prop_name, vmin, vmax)
        params["t"] = top
        with self.driver.session() as session:
            rows = list(session.run(
                f"MATCH (m:Material)-[r:HAS_PROPERTY]->(p:Property {{name:$p}}) "
                f"WHERE {where} "
                f"RETURN m.name AS n, "
                f"       [v IN r.value WHERE v >= $vmin AND v <= $vmax] AS vals, "
                f"       r.unit AS u "
                f"ORDER BY m.name LIMIT $t", **params))
        return [(r["n"], r["vals"], r["u"]) for r in rows]

    def count_filtered(self, prop_name, vmin=None, vmax=None):
        """只统计符合条件的材料个数（用于回答『有几个』）"""
        where, params = self._prop_where(prop_name, vmin, vmax)
        with self.driver.session() as session:
            r = session.run(
                f"MATCH (m:Material)-[r:HAS_PROPERTY]->(p:Property {{name:$p}}) "
                f"WHERE {where} RETURN count(DISTINCT m) AS c",
                **params).single()
        return r["c"] if r else 0

    # ---------------- 新增：图谱统计 ----------------
    def corpus_stats(self, kind):
        """图谱统计量。kind 见下表，未知 kind 返回 None"""
        Q = {
            "material": "MATCH (n:Material) RETURN count(n) AS c",
            "publication": "MATCH (n:Publication) RETURN count(n) AS c",
            "method": "MATCH (n:Method) RETURN count(n) AS c",
            "application": "MATCH (n:Application) RETURN count(n) AS c",
            "evidence": "MATCH (n:Evidence) RETURN count(n) AS c",
            "property": "MATCH (n:Property) RETURN count(n) AS c",
            "relation": "MATCH ()-[r]->() RETURN count(r) AS c",
            "material_studied":
                "MATCH (m:Material)-[:STUDIES]-() "
                "RETURN count(DISTINCT m) AS c",
            "material_without_study":
                "MATCH (m:Material) WHERE NOT (m)-[:STUDIES]-() "
                "RETURN count(m) AS c",
            "material_with_pce":
                "MATCH (m:Material)-[:HAS_PROPERTY]->(p:Property {name:'PCE'}) "
                "RETURN count(DISTINCT m) AS c",
            "material_with_bandgap":
                "MATCH (m:Material)-[:HAS_PROPERTY]->"
                "(p:Property {name:'Bandgap'}) RETURN count(DISTINCT m) AS c",
            # 按关系类型统计（不能只给总数，否则"有多少 HAS_PROPERTY 关系"答不了）
            "has_property": "MATCH ()-[r:HAS_PROPERTY]->() RETURN count(r) AS c",
            "characterized_by":
                "MATCH ()-[r:CHARACTERIZED_BY]->() RETURN count(r) AS c",
            "studies": "MATCH ()-[r:STUDIES]->() RETURN count(r) AS c",
            "has_evidence":
                "MATCH ()-[r:HAS_EVIDENCE]->() RETURN count(r) AS c",
            "related_to": "MATCH ()-[r:RELATED_TO]->() RETURN count(r) AS c",
            "used_in": "MATCH ()-[r:USED_IN]->() RETURN count(r) AS c",
            "doped_with": "MATCH ()-[r:DOPED_WITH]->() RETURN count(r) AS c",
            "from_publication":
                "MATCH ()-[r:FROM_PUBLICATION]->() RETURN count(r) AS c",
        }
        q = Q.get(kind)
        if not q:
            return None
        with self.driver.session() as session:
            r = session.run(q).single()
        return r["c"] if r else 0

    def top_properties(self, top=10):
        """被最多材料报道的性能"""
        with self.driver.session() as session:
            return [(r["n"], r["c"]) for r in session.run(
                "MATCH (m:Material)-[:HAS_PROPERTY]->(p:Property) "
                "RETURN p.name AS n, count(DISTINCT m) AS c "
                "ORDER BY c DESC LIMIT $t", t=top)]

    def top_methods(self, top=10):
        """被最多材料使用的方法"""
        with self.driver.session() as session:
            return [(r["n"], r["c"]) for r in session.run(
                "MATCH (m:Material)-[:CHARACTERIZED_BY]->(me:Method) "
                "RETURN me.name AS n, count(DISTINCT m) AS c "
                "ORDER BY c DESC LIMIT $t", t=top)]

    def top_materials(self, top=10):
        """被最多文献研究的材料"""
        with self.driver.session() as session:
            return [(r["n"], r["c"]) for r in session.run(
                "MATCH (p:Publication)-[:STUDIES]->(m:Material) "
                "RETURN m.name AS n, count(DISTINCT p) AS c "
                "ORDER BY c DESC LIMIT $t", t=top)]

    def material_exists(self, name):
        """该材料名是否精确存在于图谱"""
        with self.driver.session() as session:
            r = session.run("MATCH (m:Material {name:$n}) RETURN count(m) AS c",
                            n=name).single()
        return bool(r and r["c"])

    def resolve_material(self, token):
        """把提问里的化学式 token 解析成图谱里的真实材料名。
        优先精确匹配；否则用名字包含该 token 的材料里 _scope=perovskite、
        且文献数最多的那个。返回 None 表示图谱里没有。"""
        if not token:
            return None
        if self.material_exists(token):
            return token
        with self.driver.session() as session:
            rows = list(session.run(
                "MATCH (m:Material) WHERE toLower(m.name) CONTAINS toLower($t) "
                "OPTIONAL MATCH (p:Publication)-[:STUDIES]->(m) "
                "RETURN m.name AS n, m._scope AS sc, count(DISTINCT p) AS k "
                "ORDER BY k DESC LIMIT 12", t=token))
        if not rows:
            return None
        order = {"perovskite": 0, "uncertain": 1, "non_absorber": 2, "generic": 3}
        rows.sort(key=lambda r: (order.get(r["sc"], 4), -r["k"]))
        return rows[0]["n"]


class Scientist:
    def __init__(self, llm_client):
        self.llm = llm_client

    @staticmethod
    def _method_lines(kg_miner, material_name, top=15):
        """方法按『被多少材料共用』排序，避免把 600+ 个方法硬截断前15个"""
        rel = kg_miner.get_material_methods_ranked(material_name)
        if not rel:
            return []
        lines = [f"{n}（{c} 个材料共用）" for n, c in rel[:top]]
        if len(rel) > top:
            lines.append(f"……共 {len(rel)} 种方法")
        return lines

    def query_material(self, user_query, material_name, kg_miner):
        props = kg_miner.get_material_properties(material_name)
        methods = self._method_lines(kg_miner, material_name)
        dopants = kg_miner.get_dopants(material_name)
        evidence = kg_miner.get_material_evidence(material_name)
        pubs = kg_miner.get_material_publications(material_name)
        # 文献总篇数：get_material_publications 默认只取最近 15 篇，
        # 若不给总数，模型会把"列表长度"当成"总篇数"而答错（如 MAPbI3 实为 284）
        n_pubs = kg_miner.count_publications_for_material(material_name)

        # 证据只摘取关键字段，避免把整段 JSON 塞进 prompt
        # 兼容 v2（平铺字典）与 v3（figures 数组）两代 schema
        ev_lines = KG_Miner._evidence_lines(evidence, top=12)
        # 按页汇总：保证每一页都出现在证据里，不被单页的大量 figure 挤掉
        ev_summary = KG_Miner._evidence_summary(evidence, top=15)

        prompt = f"""你是钙钛矿材料科学家。用户问关于 {material_name} 的问题，基于证据回答。

Answer in English. All output text (answer, evidence_used, limitations, reason) must be written in English.


用户问题：{user_query}
材料：{material_name}

【性能数据（已按最大值/均值统计，越界值已隔离）】
{chr(10).join(props[:20]) if props else '无'}

【合成与表征方法（按通用程度排序）】
{chr(10).join(methods) if methods else '无'}

【掺杂】
{', '.join(dopants[:10]) if dopants else '无'}

【图像证据（按页汇总，这是全部页码）】
{chr(10).join(ev_summary) if ev_summary else '无'}

【图像证据（含数值的样例）】
{chr(10).join(ev_lines) if ev_lines else '无'}

【来源文献】
图谱中共有 {n_pubs} 篇文献研究了 {material_name}。
下面只列出最近 {len(pubs)} 篇作为示例，**总数以上面的 {n_pubs} 为准**：
{chr(10).join(pubs) if pubs else '（无）'}

要求：
1. 如果有多个数值，说明最高值与来源文献数量，不要只给一个孤立数字
2. 如果证据不足，明确说"证据有限"
3. 回答时说明依据
4. 如果用户问的是"哪些文献/出处/DOI"，直接列出上面【来源文献】里的条目
5. **如果用户问"有多少篇文献研究某材料"，必须回答 {n_pubs}，不能回答列表长度**
6. 如果用户问"有哪些图像证据/在哪几页"，必须依据【按页汇总】列举**全部页码**，
   不能只看【含数值的样例】就下结论说只有一页
输出 JSON：{{"answer": "回答内容", "evidence_used": "引用证据摘要", "limitations": ""}}
"""
        # 证据正文单存一份：Editor 展示与 Critic 核对都用它，口径完全一致
        evidence_text = (
            f"【性能数据】\n{chr(10).join(props[:20]) if props else '无'}\n\n"
            f"【合成与表征方法】\n{chr(10).join(methods) if methods else '无'}\n\n"
            f"【掺杂】\n{', '.join(dopants[:10]) if dopants else '无'}\n\n"
            f"【图像证据（按页汇总）】\n"
            f"{chr(10).join(ev_summary) if ev_summary else '无'}\n\n"
            f"【图像证据（含数值的样例）】\n"
            f"{chr(10).join(ev_lines) if ev_lines else '无'}\n\n"
            f"【来源文献】共 {n_pubs} 篇（下列为最近 {len(pubs)} 篇示例）\n"
            f"{chr(10).join(pubs) if pubs else '无'}"
        )
        try:
            response = self.llm.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "system", "content": "You are a materials scientist. Output JSON only, in English."},
                          {"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=LLM_MAX_TOKENS,
                response_format={"type": "json_object"}
            )
            out = json.loads(response.choices[0].message.content)
        except Exception as e:
            out = {"answer": f"分析失败: {e}", "evidence_used": "", "limitations": ""}
        out["_evidence_bundle"] = {"materials": [material_name],
                                   "raw": evidence_text}
        return out

    def search_materials_answer(self, user_query, keyword, cands, kg_miner):
        """material_search 命中候选后：拉这些材料的真实数据，交给 LLM 归纳作答。
        不再只回一个材料名列表。"""
        lines = []
        ev_all = []
        for mm in cands[:8]:
            try:
                # get_material_properties 返回已格式化的字符串列表（含单位/样本数）
                props = kg_miner.get_material_properties(mm, top=6) or []
            except Exception:
                props = []
            try:
                ev = kg_miner.get_material_evidence(mm) or []
            except Exception:
                ev = []
            try:
                pb = kg_miner.get_material_publications(mm, top=6) or []
            except Exception:
                pb = []
            ev_all.extend(ev)
            props_txt = "; ".join(props) if props else "无结构化数值"
            pub_txt = ("；来源文献：" + " / ".join(pb)) if pb else ""
            lines.append(f"- {mm}：{props_txt}{pub_txt}")

        ev_lines = KG_Miner._evidence_lines(ev_all, top=15)
        ev_text = "\n".join(ev_lines) if ev_lines else "（无图表证据）"
        data_text = "\n".join(lines) if lines else "（无性能数据）"

        prompt = f"""你是钙钛矿材料科学家。用户在检索"含 {keyword} 的材料"。

Answer in English. All output text (answer, evidence_used, limitations, reason) must be written in English.


用户问题：{user_query}
检索关键词：{keyword}
命中的候选材料：{', '.join(cands[:8])}

【这些材料的性能数据（来自知识图谱，已统计）】
{data_text}

【图表证据（从论文原图读取）】
{ev_text}

要求：
1. 只根据上面给出的数据回答，**不要**用你自己的先验知识补充数值
2. 逐个说明命中的材料是什么、有什么数据
3. 如果某项数据缺失，直接说缺失，不要编造
4. 如果候选里有明显不是材料的条目（如"xxx layer"这种描述），指出来
5. **如果用户问的是"哪些文献研究了某材料"或要 DOI，直接列出数据里【来源文献】的条目**
6. 回答控制在 400 字内

输出 JSON：
{{"answer": "回答正文", "evidence_used": "用到的关键证据（简要）",
  "limitations": "数据不足之处"}}"""

        try:
            r = self.llm.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "system",
                           "content": "You are a materials science literature analysis expert. Output JSON only, in English."},
                          {"role": "user", "content": prompt}],
                temperature=0.2, max_tokens=LLM_MAX_TOKENS,
                response_format={"type": "json_object"})
            out = json.loads(r.choices[0].message.content or "{}")
        except Exception as e:
            out = {"answer": f"归纳失败: {type(e).__name__}: {str(e)[:120]}",
                   "evidence_used": "", "limitations": ""}
        out["_evidence_bundle"] = {
            "materials": list(cands[:8]),
            "raw": (f"【材料性能与来源文献】\n{data_text}\n\n"
                    f"【图表证据】\n{ev_text}")}
        return out

    def compare_materials(self, user_query, materials, kg_miner):
        m1, m2 = materials[0], materials[1] if len(materials) >= 2 else None
        if not m2:
            return {"answer": "需要两种材料才能对比", "evidence_used": "",
                    "_evidence_bundle": {}}

        props1 = kg_miner.get_material_properties(m1)
        props2 = kg_miner.get_material_properties(m2)
        num1 = kg_miner.get_material_properties_numeric(m1)
        num2 = kg_miner.get_material_properties_numeric(m2)

        # 程序化对比关键指标，避免 LLM 挑错数值
        key_metrics = ["PCE", "PCE_certified", "Voc", "Jsc", "FF", "Bandgap"]
        numeric_lines = []
        for k in key_metrics:
            a, b = num1.get(k), num2.get(k)
            if not a and not b:
                continue
            fa = f"{a['max']}{a['unit'] or ''}(n={a['n']})" if a else "无数据"
            fb = f"{b['max']}{b['unit'] or ''}(n={b['n']})" if b else "无数据"
            winner = ""
            if a and b and k in ("PCE", "PCE_certified", "Voc", "Jsc", "FF"):
                if a["max"] > b["max"]:
                    winner = f" -> {m1} 更高"
                elif b["max"] > a["max"]:
                    winner = f" -> {m2} 更高"
                else:
                    winner = " -> 持平"
            numeric_lines.append(f"- {k}: {m1}={fa} | {m2}={fb}{winner}")

        prompt = f"""对比 {m1} 和 {m2}，基于证据生成对比结论。

Answer in English. All output text (answer, evidence_used, limitations, reason) must be written in English.


【关键指标的数值对比（已按最大值统计，越界值已剔除）】
{chr(10).join(numeric_lines) if numeric_lines else '（图谱中缺少可直接对比的数值）'}

【{m1} 全部性能】
{chr(10).join(props1[:20]) if props1 else '无'}

【{m2} 全部性能】
{chr(10).join(props2[:20]) if props2 else '无'}

要求：结论必须以上面的数值对比为准，不要自行推断数值。
输出 JSON：{{"answer": "对比结论", "evidence_used": "引用证据摘要"}}
"""
        numeric_evidence = (
            f"【关键指标数值对比】\n"
            f"{chr(10).join(numeric_lines) if numeric_lines else '（无）'}\n\n"
            f"【{m1} 全部性能】\n{chr(10).join(props1[:20]) if props1 else '无'}\n\n"
            f"【{m2} 全部性能】\n{chr(10).join(props2[:20]) if props2 else '无'}"
        )
        try:
            response = self.llm.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "system", "content": "You are a materials scientist. Output JSON only, in English."},
                          {"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=LLM_MAX_TOKENS,
                response_format={"type": "json_object"}
            )
            out = json.loads(response.choices[0].message.content)
        except Exception as e:
            out = {"answer": f"对比分析失败: {e}", "evidence_used": ""}
        out["_evidence_bundle"] = {"materials": [m1, m2], "raw": numeric_evidence}
        return out

    # ---------------- 新增：语料统计 ----------------
    def answer_statistics(self, user_query, stat_kind, kg_miner, materials=None):
        """回答图谱统计类问题。materials 非空时用于按材料统计文献数"""
        LABEL = {
            "material": "Material nodes",
            "publication": "Publication nodes",
            "method": "Method nodes",
            "application": "Application nodes",
            "evidence": "Evidence nodes",
            "property": "Property (type) nodes",
            "relation": "relationships (all types)",
            "has_property": "HAS_PROPERTY relationships",
            "characterized_by": "CHARACTERIZED_BY relationships",
            "studies": "STUDIES relationships",
            "has_evidence": "HAS_EVIDENCE relationships",
            "related_to": "RELATED_TO relationships",
            "used_in": "USED_IN relationships",
            "doped_with": "DOPED_WITH relationships",
            "from_publication": "FROM_PUBLICATION relationships",
            "material_studied": "materials linked to at least one publication",
            "material_without_study": "materials with no linked research data",
            "material_with_pce": "materials with a reported PCE",
            "material_with_bandgap": "materials with a reported bandgap",
        }
        facts = []
        if stat_kind == "material":
            tot = kg_miner.corpus_stats("material") or 0
            studied = kg_miner.corpus_stats("material_studied") or 0
            unstudied = kg_miner.corpus_stats("material_without_study") or 0
            facts += [f"total Material nodes: {tot}",
                      f"Material nodes linked to at least one publication: {studied}",
                      f"Material nodes with no linked research data: {unstudied}"
                      + (f" ({round(unstudied / tot * 100, 1)}%)" if tot else "")]
            # 全量性能覆盖榜：不要再硬编码 PCE/Bandgap，否则 Mobility 之类答不了
            tp = kg_miner.top_properties(20)
            if tp:
                facts.append("property coverage (number of materials reporting "
                             "each property):")
                facts += [f"  {n}: {c} materials" for n, c in tp]
            # 研究热度榜：回答"哪些材料被研究最多"
            tm = kg_miner.top_materials(10)
            if tm:
                facts.append("most studied materials (number of publications):")
                facts += [f"  {n}: {c} publications" for n, c in tm]
        elif stat_kind == "property":
            facts.append(f"distinct Property types: "
                         f"{kg_miner.corpus_stats('property')}")
            facts += [f"  {n}: reported by {c} materials"
                      for n, c in kg_miner.top_properties(15)]
        elif stat_kind == "method":
            facts.append(f"distinct Method nodes: "
                         f"{kg_miner.corpus_stats('method')}")
            facts += [f"  {n}: used by {c} materials"
                      for n, c in kg_miner.top_methods(10)]
        elif stat_kind == "publication":
            facts.append(f"total Publication nodes: "
                         f"{kg_miner.corpus_stats('publication')}")
            if materials:
                for m in materials[:5]:
                    facts.append(
                        f"publications studying {m}: "
                        f"{kg_miner.count_publications_for_material(m)}")
            tm = kg_miner.top_materials(10)
            if tm:
                facts.append("most studied materials (number of publications):")
                facts += [f"  {n}: {c} publications" for n, c in tm]
        elif stat_kind in ("top_materials", "top_properties", "top_methods"):
            # 排行榜类问题：必须直接给出排名，不能只回一个总数
            if stat_kind == "top_materials":
                facts.append("materials studied by the largest number of "
                             "publications:")
                facts += [f"  {n}: {c} publications"
                          for n, c in kg_miner.top_materials(10)]
            elif stat_kind == "top_properties":
                facts.append("most frequently reported properties "
                             "(number of materials reporting each):")
                facts += [f"  {n}: {c} materials"
                          for n, c in kg_miner.top_properties(10)]
            else:
                facts.append("methods associated with the largest number of "
                             "materials:")
                facts += [f"  {n}: {c} materials"
                          for n, c in kg_miner.top_methods(10)]
        elif stat_kind in LABEL and stat_kind not in (
                "material", "publication", "method", "property"):
            # 关系类型 / 单一节点类型：直接给一个数
            v = kg_miner.corpus_stats(stat_kind)
            if v is None:
                v = 0
            facts.append(f"{LABEL[stat_kind]}: {v}")
            if stat_kind == "relation":
                facts.append("breakdown by relationship type:")
                for k in ("has_property", "characterized_by", "studies",
                          "has_evidence", "related_to", "used_in",
                          "doped_with", "from_publication"):
                    facts.append(f"  {LABEL[k]}: {kg_miner.corpus_stats(k)}")
            # 比例类问题：同时给出分母和百分比
            if stat_kind in ("material_studied", "material_without_study"):
                tot = kg_miner.corpus_stats("material") or 1
                facts.append(f"total Material nodes: {tot}")
                facts.append(f"share: {round(v / tot * 100, 1)} percent")
        else:
            for k in ("material", "publication", "method", "application",
                      "evidence", "relation"):
                facts.append(f"{LABEL[k]}: {kg_miner.corpus_stats(k)}")
            facts.append("breakdown by relationship type:")
            for k in ("has_property", "characterized_by", "studies",
                      "has_evidence", "related_to", "used_in", "doped_with"):
                facts.append(f"  {LABEL[k]}: {kg_miner.corpus_stats(k)}")
            tm = kg_miner.top_materials(5)
            if tm:
                facts.append("most studied materials: "
                             + ", ".join(f"{n} ({c} publications)" for n, c in tm))

        facts = [f for f in facts if f]
        ev = "【图谱统计量】\n" + "\n".join(facts)
        prompt = f"""你是钙钛矿材料科学家。用户问的是知识图谱的统计量，请依据给出的统计数字回答。

Answer in English.

用户问题：{user_query}

{ev}

要求：
1. 直接给出数字，不要含糊
2. 如果问的统计量不在上面的列表里，明确说明"该统计量不在图谱覆盖范围内"
输出 JSON：{{"answer": "回答内容", "evidence_used": "引用证据摘要", "limitations": ""}}
"""
        try:
            response = self.llm.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "system", "content": "You are a data analyst. Output JSON only, in English."},
                          {"role": "user", "content": prompt}],
                temperature=0.1, max_tokens=LLM_MAX_TOKENS,
                response_format={"type": "json_object"})
            out = json.loads(response.choices[0].message.content)
        except Exception as e:
            out = {"answer": f"统计失败: {e}", "evidence_used": "",
                   "limitations": ""}
        out["_evidence_bundle"] = {"raw": ev}
        return out

    # ---------------- 新增：按性能数值筛选 ----------------
    def filter_property_answer(self, user_query, prop, vmin, vmax, kg_miner):
        """按性能数值范围筛选材料并作答"""
        n = kg_miner.count_filtered(prop, vmin, vmax)
        rows = kg_miner.filter_by_property(prop, vmin, vmax, top=25)
        rt = []
        if vmin is not None:
            rt.append(f">= {vmin}")
        if vmax is not None:
            rt.append(f"<= {vmax}")
        range_s = " and ".join(rt) or "(no bound)"
        lines = [f"{m} | matching values: {vals} {u or ''}".strip()
                 for m, vals, u in rows]
        ev = (f"【筛选条件】property={prop}, 数值落在 {range_s} 之内\n"
              f"【命中材料数】{n}\n"
              f"【命中材料明细（最多 25 条，含各自命中的数值）】\n"
              + ("\n".join(lines) if lines else "无"))
        prompt = f"""你是钙钛矿材料科学家。用户想按性能数值范围筛选材料，请依据检索结果回答。

Answer in English.

用户问题：{user_query}

{ev}

要求：
1. 先给出符合条件的材料【总数】，必须与【命中材料数】一致
2. 然后列出材料名及其命中的具体数值
3. 如果总数为 0，明确说"图谱中没有材料满足该条件"
4. 不要把只是数值区间较宽的材料混进来，只报上面列出的命中材料
输出 JSON：{{"answer": "回答内容", "evidence_used": "引用证据摘要", "limitations": ""}}
"""
        try:
            response = self.llm.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "system", "content": "You are a materials scientist. Output JSON only, in English."},
                          {"role": "user", "content": prompt}],
                temperature=0.1, max_tokens=LLM_MAX_TOKENS,
                response_format={"type": "json_object"})
            out = json.loads(response.choices[0].message.content)
        except Exception as e:
            out = {"answer": f"筛选失败: {e}", "evidence_used": "",
                   "limitations": ""}
        out["_evidence_bundle"] = {"raw": ev}
        return out


class Critic:
    """
    审查者：只判断「回答是否忠于给定证据」，不得引入模型自身的外部知识。
    修复记录：旧版本只收到回答、收不到证据，导致它用训练记忆否定图谱数据
    （实测中把基于 292 条文献统计的 PCE=31% 判为错误），故现在必须传入证据包。
    """
    def __init__(self, llm_client):
        self.llm = llm_client

    @staticmethod
    def _format_evidence(bundle):
        if not bundle:
            return "（无证据包）"
        # 首选：Scientist 实际看到的证据原文，保证两边口径一致
        if bundle.get("raw"):
            return str(bundle["raw"])
        # 退化路径：手工拼装
        lines = []
        mats = bundle.get("materials")
        if mats:
            lines.append(f"涉及材料: {', '.join(mats)}")
        if bundle.get("numeric_comparison"):
            lines.append("数值对比:")
            lines += [f"  {x}" for x in bundle["numeric_comparison"]]
        props = bundle.get("properties")
        if isinstance(props, dict):
            for k, v in props.items():
                lines.append(f"{k} 的性能:")
                lines += [f"  {x}" for x in (v or [])]
        elif props:
            lines.append("性能:")
            lines += [f"  {x}" for x in props]
        if bundle.get("methods"):
            lines.append("方法: " + "; ".join(bundle["methods"]))
        if bundle.get("dopants"):
            lines.append("掺杂: " + ", ".join(bundle["dopants"]))
        if bundle.get("image_evidence"):
            lines.append("图像证据:")
            lines += [f"  {x}" for x in bundle["image_evidence"]]
        return "\n".join(lines) if lines else "（无证据包）"

    def review(self, scientist_output, user_query=""):
        evidence = self._format_evidence(scientist_output.get("_evidence_bundle"))
        prompt = f"""你是审查者。你的唯一职责是判断下面的「回答」是否忠实于「证据」。

Answer in English. All output text (answer, evidence_used, limitations, reason) must be written in English.


用户问题：{user_query}

证据（来自钙钛矿材料知识图谱，是本次回答的唯一依据）：
{evidence}

待审查的回答：
{scientist_output.get('answer', '')}

审查规则（严格按此执行）：
1. **只比对回答与证据是否一致**。回答中的数值若能在证据中找到出处，即为正确。
2. **禁止用你自己的先验知识否定证据**。知识图谱的值来自文献统计，
   可能与你的记忆不符（例如图谱显示某个材料的最高 PCE 达 31%），
   但那是文献中的真实报道值，**不得据此判为错误**。
3. 回答答非所问、或凭空编造证据中不存在的数值/材料 → 判 REVISE。
4. 回答正确引用证据、或明确说明"证据有限" → 判 PASS。

输出 JSON：{{"verdict": "PASS" 或 "REVISE", "reason": "简短理由（须指出具体依据）"}}
"""
        try:
            response = self.llm.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "system", "content": "You are a review expert. Output JSON only, in English."},
                          {"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=LLM_MAX_TOKENS,
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            return {"verdict": "REVISE", "reason": f"审查失败: {e}"}


class Editor:
    """
    编辑者：整合 Scientist 与 Critic 的输出，生成最终结构化报告。
    （论文将 Editor 列为五个智能体之一，这里实现为确定性组件——
      它做的是格式整合与一致性检查，不需要 LLM 参与，也不会引入新内容。）
    """
    def __init__(self):
        pass

    def compile_report(self, user_query, materials, scientist_output, review):
        answer = scientist_output.get("answer", "")
        limitations = scientist_output.get("limitations", "")
        bundle = scientist_output.get("_evidence_bundle") or {}

        # 从证据包里提取可读的证据摘要
        ev_bits = []
        if bundle.get("numeric_comparison"):
            ev_bits += bundle["numeric_comparison"]
        props = bundle.get("properties")
        if isinstance(props, dict):
            for k, v in props.items():
                if v:
                    ev_bits.append(f"{k}: " + "; ".join(str(x) for x in v[:3]))
        elif props:
            ev_bits += [str(x) for x in props[:6]]

        return {
            "user_query": user_query,
            "materials": materials,
            "answer": answer,
            "evidence": "\n".join(ev_bits) if ev_bits else (scientist_output.get("evidence_used") or "无"),
            "limitations": limitations,
            "review": review,
        }



def generate_markdown_report(answer, evidence, materials, user_query,
                             limitations="", verdict="", review_reason=""):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    md = f"# 钙钛矿材料分析报告\n\n"
    md += f"**生成时间**: {timestamp}\n\n"
    md += f"**用户问题**: {user_query}\n\n"
    md += f"**涉及材料**: {', '.join(materials) if materials else '无'}\n\n"
    md += f"## 回答\n\n{answer}\n\n"
    md += f"## 引用证据\n\n{evidence if evidence else '无'}\n\n"
    if limitations:
        md += f"## 局限性说明\n\n{limitations}\n\n"
    if verdict:
        md += f"## 审查结果\n\n**{verdict}** — {review_reason}\n"
    md += "\n---\n*报告由钙钛矿多智能体系统自动生成"
    md += "（Planner → KG-Miner → Scientist → Critic → Editor）*"
    return md


# 初始化 session_state
if "report_data" not in st.session_state:
    st.session_state.report_data = None
if "materials" not in st.session_state:
    st.session_state.materials = []
if "user_query" not in st.session_state:
    st.session_state.user_query = ""


with st.sidebar:
    st.header("🔍 Input")
    user_query = st.text_input(
        "What would you like to ask?",
        value="What is the highest PCE of MAPbI3?",
        placeholder="e.g. What is the highest PCE of MAPbI3?"
    )
    analyze_button = st.button("🚀 Analyze", type="primary", use_container_width=True)
    st.markdown("---")
    st.caption("💡 Example: What is the highest PCE of MAPbI3?")
    st.caption("💡 Example: Compare MAPbI3 and FAPbI3")
    st.caption("💡 Example: How is MAPbI3 fabricated?")

if analyze_button and user_query:
    with st.spinner("🧠 Calling the multi-agent system..."):
        try:
            planner = Planner(llm_client)
            kg_miner = KG_Miner(driver)
            scientist = Scientist(llm_client)
            critic = Critic(llm_client)
            editor = Editor()

            with st.status("🧠 Planner is planning the task...", expanded=True) as status:
                plan = planner.plan(user_query)
                status.update(label=f"✅ Task type: {plan.get('task_type', 'unknown')}")

            st.info(f"📋 Plan: {plan.get('intent', 'n/a')}")
            if plan.get("_dropped_category_terms"):
                st.caption(f"ℹ️ Ignored generic (non-specific) terms: {plan['_dropped_category_terms']}")

            materials = plan.get("materials", [])
            task_type = plan.get("task_type", "general")

            # 校验层：Planner 给出的材料名若不在图谱里，从问句里回退解析。
            # 防止把 CH3NH3GeI3 误写成 MAPbI3 这类化学组成错误，
            # 也防止把 APbI 擅自"补全"成 APbI3。
            if materials:
                fixed, notes = [], []
                for m in materials:
                    if kg_miner.material_exists(m):
                        fixed.append(m)
                        continue
                    alt = None
                    for tok in _KW_FORMULA.findall(user_query):
                        alt = kg_miner.resolve_material(tok)
                        if alt and alt not in fixed:
                            break
                        alt = None
                    if alt:
                        fixed.append(alt)
                        notes.append(f"{m} -> {alt}")
                    else:
                        fixed.append(m)
                if notes:
                    plan["_material_repaired"] = notes
                    materials = fixed
                    plan["materials"] = fixed
                    try:                       # 库版本（无 Streamlit）下跳过
                        st.caption("ℹ️ Material name corrected: "
                                   + "; ".join(notes))
                    except NameError:
                        pass

            if task_type == "material_query" and materials:
                with st.status("🔬 Scientist is querying...", expanded=True) as status:
                    result = scientist.query_material(user_query, materials[0], kg_miner)
                    status.update(label="✅ Query complete")
            elif task_type == "material_compare" and len(materials) >= 2:
                with st.status("🔬 Scientist is comparing...", expanded=True) as status:
                    result = scientist.compare_materials(user_query, materials, kg_miner)
                    status.update(label="✅ Comparison complete")
            elif task_type == "material_search":
                keyword = str(plan.get("search_keyword") or "").strip()
                if keyword:
                    with st.status(f"🔍 Retrieving materials containing \"{keyword}\"...",
                                   expanded=True) as status:
                        cands = kg_miner.search_materials(keyword)
                        status.update(label=f"✅ Found {len(cands)} related materials")
                    if cands:
                        # 有命中：交给 Scientist 基于真实数据归纳，而不是只回列表
                        result = scientist.search_materials_answer(
                            user_query, keyword, cands, kg_miner)
                    else:
                        result = {
                            "answer": f"图谱中没有找到名称含「{keyword}」的材料。"
                                      "可以换个关键词，或指定具体材料"
                                      "（如 MAPbI3、FAPbI3、CsPbI3）。",
                            "evidence_used": "", "_evidence_bundle": {},
                        }
                else:
                    # 连关键词都抠不出来：明确告知，不再返回无关材料充数
                    with st.status("🔍 Retrieving candidate materials...", expanded=True) as status:
                        sample = kg_miner.search_materials("")
                        status.update(label="✅ Sample materials retrieved")
                    result = {
                        "answer": "这个问题针对的是一类材料而非具体组分，"
                                  "我没能从中提取出可用于检索的关键词。"
                                  "请换个说法（例如「C60 相关的材料」「含 Sn 的钙钛矿」），"
                                  "或直接指定具体材料（如 MAPbI3、FAPbI3、CsPbI3）。"
                                  f"\n\n图谱中的材料示例：{', '.join(sample[:12]) if sample else '（查询失败）'}",
                        "evidence_used": "", "_evidence_bundle": {},
                    }
            elif task_type == "property_filter":
                pname = str(plan.get("property_name") or "").strip()
                pmin = plan.get("property_min")
                pmax = plan.get("property_max")
                if pname:
                    with st.status(f"🔎 Filtering materials by {pname}...",
                                   expanded=True) as status:
                        result = scientist.filter_property_answer(
                            user_query, pname, pmin, pmax, kg_miner)
                        status.update(label=f"✅ Filtered on {pname}")
                else:
                    result = {
                        "answer": "没能识别出要筛选的性能名称。请指定性能"
                                  "（如 PCE、Voc、Bandgap、FF、Jsc）和数值范围。",
                        "evidence_used": "", "_evidence_bundle": {},
                    }
            elif task_type == "corpus_statistics":
                stat_kind = str(plan.get("stat_kind") or "").strip()
                with st.status("📊 Retrieving graph statistics...",
                               expanded=True) as status:
                    result = scientist.answer_statistics(
                        user_query, stat_kind, kg_miner, materials)
                    status.update(label="✅ Statistics retrieved")
            else:
                # 图谱覆盖范围之外的问题：明确声明边界，而不是报故障
                result = {
                    "answer": (
                        "This system answers questions that can be grounded in the "
                        "constructed knowledge graph. The graph covers materials, "
                        "properties, methods, applications, publications and image "
                        "evidence extracted from the perovskite solar cell "
                        "literature corpus. The question asks for information "
                        "outside this scope, so it cannot be answered from the "
                        "corpus. Please rephrase the question so that it targets "
                        "materials, performance values, synthesis or "
                        "characterization methods, applications, or source "
                        "publications covered by the graph."
                    ),
                    "evidence_used": "",
                    "limitations": ("The question falls outside the coverage of the "
                                    "knowledge graph."),
                    "_evidence_bundle": {},
                }

            # Critic 必须拿到证据包，否则会凭自身记忆误判
            with st.status("🔍 Critic is reviewing...", expanded=True) as status:
                review = critic.review(result, user_query)
                status.update(label=f"✅ Review complete: {review.get('verdict', 'UNKNOWN')}")

            # Editor 整合输出
            with st.status("📝 Editor is compiling the report...", expanded=True) as status:
                report = editor.compile_report(user_query, materials, result, review)
                status.update(label="✅ Report generated")

            st.session_state.report_data = report
            st.session_state.materials = materials
            st.session_state.user_query = user_query

            st.markdown("---")
            st.header("📄 Analysis Result")

            verdict = review.get("verdict", "UNKNOWN")
            if verdict == "PASS":
                st.success("✅ Verdict: Approved")
            else:
                st.warning(f"⚠️ Verdict: Needs revision — {review.get('reason', '')}")

            st.subheader("📝 Answer")
            st.write(report.get("answer", "N/A"))

            with st.expander("📊 View supporting evidence"):
                st.write(report.get("evidence", "N/A"))
            if report.get("limitations"):
                with st.expander("⚠️ Limitations"):
                    st.write(report["limitations"])

        except Exception as e:
            st.error(f"Error: {e}")
            st.stop()

# 导出报告
if st.session_state.report_data:
    st.markdown("---")
    st.subheader("📥 Export Report")
    rd = st.session_state.report_data
    rev = rd.get("review") or {}
    md_report = generate_markdown_report(
        rd.get("answer", ""),
        rd.get("evidence", ""),
        rd.get("materials") or st.session_state.materials,
        rd.get("user_query") or st.session_state.user_query,
        limitations=rd.get("limitations", ""),
        verdict=rev.get("verdict", ""),
        review_reason=rev.get("reason", ""),
    )
    st.download_button(
        label="📥 Download Markdown Report",
        data=md_report.encode('utf-8'),
        file_name=f"报告_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
        mime="text/markdown",
        key="download_md"
    )

st.markdown("---")
st.caption("Data source: Perovskite Literature Knowledge Graph | Multi-Agent System: Planner → KG-Miner → Scientist → Critic → Editor")