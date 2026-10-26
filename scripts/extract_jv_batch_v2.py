import json
import base64
from pathlib import Path
from pdf2image import convert_from_path
import dashscope
from dashscope import MultiModalConversation
from neo4j import GraphDatabase
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
INTERSECTION_FILE = Path(r"C:\Users\20155\dpa4_project\data\intersection_dois.txt")
OUTPUT_DIR = Path(r"C:\Users\20155\dpa4_project\data\multimodal_hd")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

POPPLER_PATH = r"C:\poppler-26.02.0\Library\bin"


def convert_pdf_to_images(pdf_path):
    images = convert_from_path(str(pdf_path), dpi=300, poppler_path=POPPLER_PATH)
    image_paths = []
    for i, img in enumerate(images):
        img_path = OUTPUT_DIR / f"{pdf_path.stem}_page{i + 1}.png"
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


def save_to_neo4j(doi, data):
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:
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
    driver.close()


def main():
    with open(INTERSECTION_FILE, 'r') as f:
        dois = [line.strip() for line in f if line.strip()]

    print(f"📚 待处理: {len(dois)} 篇文献")
    success = 0
    failed = 0

    for doi in dois:
        pdf_path = PDF_DIR / f"{doi.replace('/', '_')}.pdf"
        if not pdf_path.exists():
            print(f"❌ 跳过: {pdf_path.name} 不存在")
            failed += 1
            continue

        print(f"\n📄 处理: {pdf_path.name}")

        try:
            page_images = convert_pdf_to_images(pdf_path)
        except Exception as e:
            print(f"   ❌ PDF 损坏或无法读取: {e}")
            failed += 1
            continue

        found = False
        for img_path in page_images:
            result = analyze_jv_from_image(img_path)
            try:
                data = json.loads(result)
                if data.get("has_jv"):
                    print(f"   ✅ 找到 J-V 曲线: PCE={data.get('PCE', 'N/A')}")
                    save_to_neo4j(doi, data)
                    success += 1
                    found = True
                    break
            except:
                continue

        if not found:
            print(f"   ⚠️ 未找到 J-V 曲线")
            failed += 1

    print(f"\n🎉 完成！成功: {success}, 失败/跳过: {failed}")


if __name__ == "__main__":
    main()