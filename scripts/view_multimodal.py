import json
from pathlib import Path

path = Path('C:/Users/20155/dpa4_project/data/multimodal_output/multimodal_results.json')

with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)

for pdf, info in data.items():
    print(f'📄 {pdf}')
    for item in info.get('analyzed', [])[:1]:
        print(f'   🖼️ 图片: {item.get("image")}')
        analysis = item.get('analysis', '')
        # 提取 JSON 内容并解析
        try:
            import json as json_lib
            parsed = json_lib.loads(analysis)
            print(f'   📝 类型: {parsed.get("image_type", "未知")}')
            print(f'   📝 信息: {parsed.get("extracted_info", "")[:150]}...')
            print(f'   📊 数值: {parsed.get("numerical_values", {})}')
        except:
            print(f'   📝 原始内容: {analysis[:200]}...')
    print()