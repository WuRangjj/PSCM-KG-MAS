import json
import base64
from pathlib import Path
from pdf2image import convert_from_path
import dashscope
from dashscope import MultiModalConversation
from neo4j import GraphDatabase
import os
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

# 已处理过的DOI（从图谱里查，已有Evidence的）
# 可以从Neo4j查出来后填这里，或者留空全部重新跑
ALREADY_PROCESSED = set()


def convert_pdf_to_images(pdf_path):
    images = convert_from_path(str(pdf_path), dpi=300, poppler_path=POPPLER_PATH)
    image_paths = []
    for i, img in enumerate(images):
        img_path = OUTPUT_DIR / f"{pdf_path.stem}_page{i+1}.png"
        img.save(img_path, "PNG")
        image_paths.append(img_path)
    return image_paths


def analyze_jv_from_image(image_path):
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


def save_to_neo4j_standalone(pdf_stem, data):
    """创建独立的Evidence节点，不关联Publication，只存source_pdf"""
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:
        # 直接用pdf_stem作为source_pdf，不创建Publication节点
        session.run("""
            CREATE (e:Evidence {
                image_type: 'J-V曲线',
                source_pdf: $pdf_stem,
                extracted_data: $data,
                confidence: 'high',
                extraction_method: 'Qwen3-VL-Flash'
            })
        """, pdf_stem=pdf_stem, data=json.dumps(data, ensure_ascii=False))
        print(f"   ✅ Evidence 节点已创建（独立，无Publication关联）")
    driver.close()


def main():
    # 获取所有PDF
    pdf_files = [f for f in PDF_DIR.glob("*.pdf") if f.is_file()]
    print(f"📚 找到 {len(pdf_files)} 个 PDF 文件")

    # 从图谱获取已有Evidence的PDF（避免重复处理）
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:
        result = session.run("MATCH (e:Evidence) RETURN e.source_pdf AS source_pdf")
        for record in result:
            ALREADY_PROCESSED.add(record["source_pdf"])
    driver.close()
    print(f"📊 已有 Evidence 的PDF数量: {len(ALREADY_PROCESSED)}")

    success = 0
    failed = 0
    skipped = 0

    for pdf_path in pdf_files:
        pdf_stem = pdf_path.stem  # 不带.pdf后缀

        # 跳过已处理的
        if pdf_stem in ALREADY_PROCESSED:
            print(f"⏭️ 跳过: {pdf_path.name} (已存在Evidence)")
            skipped += 1
            continue

        print(f"\n📄 处理: {pdf_path.name}")

        try:
            page_images = convert_pdf_to_images(pdf_path)
        except Exception as e:
            print(f"   ❌ PDF损坏: {e}")
            failed += 1
            continue

        found = False
        for img_path in page_images:
            result = analyze_jv_from_image(img_path)
            try:
                data = json.loads(result)
                if data.get("has_jv"):
                    print(f"   ✅ 找到 J-V 曲线: PCE={data.get('PCE', 'N/A')}")
                    save_to_neo4j_standalone(pdf_stem, data)
                    success += 1
                    found = True
                    break
            except:
                continue

        if not found:
            print(f"   ⚠️ 未找到 J-V 曲线")
            failed += 1

    print(f"\n🎉 完成！成功: {success}, 失败: {failed}, 跳过: {skipped}")


if __name__ == "__main__":
    main()