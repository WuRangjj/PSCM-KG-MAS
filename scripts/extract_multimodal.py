import json
import base64
from pathlib import Path
import fitz  # PyMuPDF
import dashscope
from dashscope import MultiModalConversation

# ========== 配置 ==========
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
dashscope.api_key = os.environ["DASHSCOPE_API_KEY"]
PDF_DIR = Path(r"C:\Users\20155\dpa4_project\data\pdfs")
OUTPUT_DIR = Path(r"C:\Users\20155\dpa4_project\data\multimodal_output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def extract_images_from_pdf(pdf_path, output_folder):
    """从 PDF 提取所有图片，过滤小图片"""
    doc = fitz.open(pdf_path)
    image_paths = []
    for page_num, page in enumerate(doc):
        # 获取当前页的所有图片
        image_list = page.get_images(full=True)
        for img_index, img in enumerate(image_list):
            xref = img[0]
            try:
                # 直接提取图片
                pix = fitz.Pixmap(doc, xref)
                if pix.width < 100 or pix.height < 100:
                    pix = None
                    continue
                # 如果是 CMYK 或其他格式，转 RGB
                if pix.n - pix.alpha > 3:
                    try:
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    except:
                        pass
                img_path = output_folder / f"page{page_num+1}_img{img_index+1}.png"
                pix.save(img_path)
                image_paths.append(img_path)
            except Exception as e:
                print(f"      ⚠️ 图片提取失败: {e}")
                continue
            finally:
                if 'pix' in locals():
                    pix = None
    doc.close()
    return image_paths


def analyze_image(image_path):
    """调用 Qwen3-VL-Flash 分析单张图片，输出结构化数据"""
    with open(image_path, 'rb') as f:
        img_base64 = base64.b64encode(f.read()).decode()

    prompt = """
【任务】分析这张图片，判断它属于哪种类型，并提取钙钛矿材料相关的关键信息。

【图片类型判断规则】
- "J-V曲线"：电流密度-电压曲线，有 Jsc、Voc、FF、PCE 等标注
- "XRD"：X射线衍射图谱，有峰位、强度、晶面指数
- "SEM"：扫描电镜图像，显示材料形貌
- "TEM"：透射电镜图像，显示晶格、缺陷
- "表格"：包含文字和数字的表格
- "示意图"：结构示意图、能级图、器件结构图
- "其他"：期刊标志、页眉页脚、无法识别的图片

【输出格式】必须严格输出以下 JSON 结构，不要有任何额外文字：
{
    "image_type": "图片类型（从上面7种选一个）",
    "extracted_data": {
        "PCE": {"value": "数值或null", "unit": "%"},
        "Voc": {"value": "数值或null", "unit": "V"},
        "Jsc": {"value": "数值或null", "unit": "mA/cm²"},
        "FF": {"value": "数值或null", "unit": "%"},
        "peak_position": {"value": "数值或null", "unit": "度(2θ)"},
        "crystal_plane": "晶面指数或null",
        "grain_size": {"value": "数值或null", "unit": "nm"},
        "lattice_spacing": {"value": "数值或null", "unit": "nm"},
        "bandgap": {"value": "数值或null", "unit": "eV"}
    },
    "text_content": "从图片中能读到的所有文字（如标题、坐标轴标签、图例）",
    "visual_description": "对图片视觉内容的简要描述（50字以内）",
    "confidence": "high/medium/low"
}

【关键规则】
1. 如果图片看不清、文字模糊、没有数值标注，所有 value 填 null。
2. 如果图片里没有钙钛矿相关信息，image_type 填 "其他"，其他字段全部填 null。
3. 不要猜测数值，只看图片中肉眼可见的标注。
4. 如果坐标轴标注模糊，PCE、Voc等值填 null，不要推测。
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
            text_content = content[0].get('text', '')
        else:
            text_content = str(content)
        return text_content
    except Exception as e:
        return json.dumps({"error": str(e)})


def main():
    pdf_files = list(PDF_DIR.glob("*.pdf"))
    print(f"📚 找到 {len(pdf_files)} 篇 PDF")

    all_results = {}

    for i, pdf_path in enumerate(pdf_files[:5], 1):
        print(f"\n[{i}/5] 处理: {pdf_path.name}")

        pdf_output = OUTPUT_DIR / pdf_path.stem
        pdf_output.mkdir(exist_ok=True)

        images = extract_images_from_pdf(pdf_path, pdf_output)
        print(f"   🖼️ 提取了 {len(images)} 张图片")

        results = []
        for img_path in images[:5]:
            print(f"      📷 分析: {img_path.name}")
            result = analyze_image(img_path)
            results.append({
                "image": img_path.name,
                "analysis": result
            })

        all_results[pdf_path.name] = {
            "total_images": len(images),
            "analyzed": results
        }

    output_file = OUTPUT_DIR / "multimodal_results_v2.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n💾 结果已保存到: {output_file}")


if __name__ == "__main__":
    main()