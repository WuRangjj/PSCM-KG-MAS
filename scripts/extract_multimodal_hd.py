import json
import base64
from pathlib import Path
from pdf2image import convert_from_path
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
OUTPUT_DIR = Path(r"C:\Users\20155\dpa4_project\data\multimodal_hd")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# poppler 路径（如果没有这个路径，稍后改）
POPPLER_PATH = r"C:\poppler-26.02.0\Library\bin"


def convert_pdf_to_images(pdf_path):
    """将 PDF 所有页面转为高清图片"""
    print(f"   🔄 正在转换 PDF 页面为图片（300 DPI）...")
    images = convert_from_path(
        str(pdf_path),
        dpi=300,
        poppler_path=POPPLER_PATH
    )

    image_paths = []
    for i, img in enumerate(images):
        img_path = OUTPUT_DIR / f"{pdf_path.stem}_page{i + 1}.png"
        img.save(img_path, "PNG")
        image_paths.append(img_path)
        print(f"      ✅ 第 {i + 1} 页已保存")

    return image_paths


def analyze_image(image_path):
    """调用 Qwen-VL 分析图片中是否包含 J-V 曲线"""
    with open(image_path, 'rb') as f:
        img_base64 = base64.b64encode(f.read()).decode()

    prompt = """分析这张图片。
如果图片中包含J-V曲线图，提取以下参数并以JSON格式输出：
{"has_jv": true, "PCE": "数值", "Voc": "数值", "Jsc": "数值", "FF": "数值"}
如果图片中没有J-V曲线，输出：{"has_jv": false}
只输出JSON，不要其他内容。"""

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
        return json.dumps({"error": str(e)})


def main():
    # 目标文件：我们验证过有 J-V 曲线的 Nature 文章
    target_pdf = PDF_DIR / "10.1038_s41586-020-2001-x.pdf"

    if not target_pdf.exists():
        print(f"❌ 文件不存在: {target_pdf}")
        print("请确认文件在 data/pdfs/ 目录下")
        return

    print(f"📄 处理: {target_pdf.name}")

    # 1. 转 PDF 为高清图片
    page_images = convert_pdf_to_images(target_pdf)
    print(f"\n📊 共转换 {len(page_images)} 页")

    # 2. 逐页分析找 J-V 曲线
    found = False
    for img_path in page_images:
        print(f"\n🔍 分析: {img_path.name}")
        result = analyze_image(img_path)
        try:
            data = json.loads(result)
            if data.get("has_jv"):
                print(f"   ✅ 找到 J-V 曲线数据:")
                print(f"      PCE: {data.get('PCE', 'N/A')}")
                print(f"      Voc: {data.get('Voc', 'N/A')}")
                print(f"      Jsc: {data.get('Jsc', 'N/A')}")
                print(f"      FF: {data.get('FF', 'N/A')}")

                # 保存结果
                output_file = OUTPUT_DIR / "jv_results.json"
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump({
                        "pdf": target_pdf.name,
                        "page": img_path.name,
                        "data": data
                    }, f, ensure_ascii=False, indent=2)
                print(f"\n💾 结果已保存到: {output_file}")
                found = True
                break
            else:
                print(f"   ⚠️ 未找到 J-V 曲线")
        except Exception as e:
            print(f"   ❌ 解析失败: {result[:80]}...")

    if not found:
        print("\n❌ 未在任何页面找到 J-V 曲线")


if __name__ == "__main__":
    main()