import json
import base64
from pathlib import Path
from pdf2image import convert_from_path
import dashscope
from dashscope import MultiModalConversation
from neo4j import GraphDatabase

# ========== 配置 ==========
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
dashscope.api_key = os.environ["DASHSCOPE_API_KEY"]
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "wr20021218"

PDF_DIR = Path(r"C:\Users\20155\dpa4_project\data\pdfs")
OUTPUT_DIR = Path(r"C:\Users\20155\dpa4_project\data\multimodal_hd")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

POPPLER_PATH = r"C:\poppler-26.02.0\Library\bin"


def convert_pdf_to_images(pdf_path):
    """将 PDF 所有页面转为高清图片"""
    print(f"   🔄 转换 PDF 为图片（300 DPI）...")
    images = convert_from_path(str(pdf_path), dpi=300, poppler_path=POPPLER_PATH)
    image_paths = []
    for i, img in enumerate(images):
        img_path = OUTPUT_DIR / f"{pdf_path.stem}_page{i + 1}.png"
        img.save(img_path, "PNG")
        image_paths.append(img_path)
    print(f"      ✅ 共 {len(image_paths)} 页")
    return image_paths


def analyze_jv_from_image(image_path):
    """调用 Qwen-VL 分析图片是否包含 J-V 曲线"""
    with open(image_path, 'rb') as f:
        img_base64 = base64.b64encode(f.read()).decode()

    prompt = """分析这张图片。如果包含J-V曲线图，提取参数并以JSON输出：
{"has_jv": true, "PCE": "数值", "Voc": "数值", "Jsc": "数值", "FF": "数值"}
如果没有J-V曲线，输出：{"has_jv": false}
只输出JSON。"""

    try:
        response = MultiModalConversation.call(
            model='qwen3-vl-flash',
            messages=[{
                'role': 'user',
                'content': [
                    {'text': prompt},
                    {'image': f'data:image/png;base64,{img_base64}'}
                ]
            }]
        )
        content = response.output.choices[0].message.content
        if isinstance(content, list):
            return content[0].get('text', '{}')
        return content
    except Exception as e:
        return json.dumps({"has_jv": False, "error": str(e)})


def save_to_neo4j(doi, data):
    """把 J-V 曲线数据写入 Neo4j 作为 Evidence 节点"""
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:
        # 检查 Publication 是否存在
        pub_check = session.run("MATCH (p:Publication {doi: $doi}) RETURN p", doi=doi)
        if not pub_check.single():
            print(f"   ⚠️ 文献 {doi} 不在图谱中，创建占位节点")
            session.run("CREATE (p:Publication {doi: $doi, title: $title})",
                        doi=doi, title=f"J-V extracted from {doi}")

        # 创建 Evidence 节点
        session.run("""
            MATCH (p:Publication {doi: $doi})
            CREATE (e:Evidence {
                image_type: 'J-V曲线',
                source_pdf: $doi,
                extracted_data: $data,
                confidence: 'high',
                extraction_method: 'Qwen3-VL-Flash'
            })
            CREATE (p)-[:HAS_EVIDENCE]->(e)
        """, doi=doi, data=json.dumps(data, ensure_ascii=False))
        print(f"   ✅ Evidence 节点已创建")
    driver.close()


def main():
    # 只处理有 PCE 记录的文献（从图谱里查的）
    # 这里先手动指定几篇已知有 J-V 曲线的
    target_dois = [
        "10.1038_s41586-020-2001-x",
        "10.1126_science.aam7093",
    ]

    total = 0
    for doi in target_dois:
        pdf_path = PDF_DIR / f"{doi}.pdf"
        if not pdf_path.exists():
            print(f"❌ 跳过: {doi}.pdf 不存在")
            continue

        print(f"\n📄 处理: {pdf_path.name}")

        # 1. 转图片
        page_images = convert_pdf_to_images(pdf_path)

        # 2. 逐页找 J-V 曲线
        found = False
        for img_path in page_images:
            result = analyze_jv_from_image(img_path)
            try:
                data = json.loads(result)
                if data.get("has_jv"):
                    print(f"   ✅ 找到 J-V 曲线: PCE={data.get('PCE', 'N/A')}")
                    # 3. 入库
                    save_to_neo4j(doi, data)
                    found = True
                    total += 1
                    break
            except:
                continue

        if not found:
            print(f"   ⚠️ 未找到 J-V 曲线")

    print(f"\n🎉 完成！共处理 {total} 篇文献的 J-V 曲线入库")


if __name__ == "__main__":
    main()