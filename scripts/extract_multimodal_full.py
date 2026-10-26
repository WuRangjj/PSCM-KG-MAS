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

ALREADY_PROCESSED = set()
success_jv = 0
success_xrd = 0
success_sem = 0
success_table = 0
failed = 0
skipped = 0


def convert_pdf_to_images(pdf_path):
    images = convert_from_path(str(pdf_path), dpi=300, poppler_path=POPPLER_PATH)
    image_paths = []
    for i, img in enumerate(images):
        img_path = OUTPUT_DIR / f"{pdf_path.stem}_page{i + 1}.png"
        img.save(img_path, "PNG")
        image_paths.append(img_path)
    return image_paths


def analyze_image_with_vision(image_path):
    with open(image_path, 'rb') as f:
        img_base64 = base64.b64encode(f.read()).decode()

    prompt = """
分析这张图片，判断它属于以下哪种类型：
1. J-V曲线：电流密度-电压曲线，含PCE、Voc、Jsc、FF
2. XRD图谱：X射线衍射图谱，含峰位、半高宽、晶面指数
3. SEM图像：扫描电镜图像，显示材料形貌、晶粒尺寸
4. 表格：包含文字和数字的表格
5. 其他：不属于以上类别

如果是J-V曲线，提取：
{"type": "J-V曲线", "PCE": "", "Voc": "", "Jsc": "", "FF": ""}

如果是XRD图谱，提取峰位、半高宽、晶面指数（如有），并用Scherrer公式计算晶粒尺寸（D = Kλ/(β cosθ)，K=0.89，λ=1.5406Å）：
{"type": "XRD", "peaks": [{"2theta": "", "FWHM": "", "hkl": "", "grain_size_nm": ""}], "dominant_phase": ""}

如果是SEM图像，估算平均晶粒尺寸和范围：
{"type": "SEM", "avg_grain_size_nm": "", "grain_size_range": "", "morphology": ""}

如果是表格：
{"type": "表格", "headers": [], "rows": []}

如果是其他：
{"type": "其他"}

只输出JSON，不要其他内容。
"""

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
        return json.dumps({"type": "其他", "error": str(e)})


def save_evidence(pdf_stem, data):
    global success_jv, success_xrd, success_sem, success_table
    img_type = data.get("type", "其他")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:
        session.run("""
            CREATE (e:Evidence {
                image_type: $img_type,
                source_pdf: $pdf_stem,
                extracted_data: $data,
                confidence: 'high',
                extraction_method: 'Qwen3-VL-Flash'
            })
        """, img_type=img_type, pdf_stem=pdf_stem, data=json.dumps(data, ensure_ascii=False))
        print(f"   ✅ {img_type} Evidence 已创建")
    driver.close()

    if img_type == "J-V曲线":
        success_jv += 1
    elif img_type == "XRD":
        success_xrd += 1
    elif img_type == "SEM":
        success_sem += 1
    elif img_type == "表格":
        success_table += 1


def main():
    global success_jv, success_xrd, success_sem, success_table, failed, skipped

    pdf_files = list(PDF_DIR.glob("*.pdf"))
    print(f"📚 找到 {len(pdf_files)} 个 PDF 文件")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:
        result = session.run("MATCH (e:Evidence) RETURN e.source_pdf AS source_pdf")
        for record in result:
            ALREADY_PROCESSED.add(record["source_pdf"])
    driver.close()
    print(f"📊 已有 Evidence 的 PDF 数量: {len(ALREADY_PROCESSED)}")

    for pdf_path in pdf_files:
        if pdf_path.name in ALREADY_PROCESSED:
            print(f"⏭️ 跳过: {pdf_path.name} (已处理)")
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
        for img_path in page_images[:10]:  # 每篇PDF最多分析10张图，避免token超限
            result = analyze_image_with_vision(img_path)
            try:
                data = json.loads(result)
                img_type = data.get("type", "其他")
                if img_type != "其他":
                    print(f"   ✅ 找到 {img_type}")
                    save_evidence(pdf_path.stem, data)
                    found = True
                    break  # 找到一张有价值的图就停止
            except Exception as e:
                continue

        if not found:
            print(f"   ⚠️ 未找到有价值图片")
            failed += 1

    print(f"\n🎉 完成！")
    print(f"   J-V 曲线: {success_jv} 篇")
    print(f"   XRD: {success_xrd} 篇")
    print(f"   SEM: {success_sem} 篇")
    print(f"   表格: {success_table} 篇")
    print(f"   失败: {failed} 篇")
    print(f"   跳过: {skipped} 篇")


if __name__ == "__main__":
    main()