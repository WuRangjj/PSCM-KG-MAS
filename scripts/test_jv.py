import json
import base64
import dashscope
from dashscope import MultiModalConversation
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
dashscope.api_key = os.environ["DASHSCOPE_API_KEY"]
with open('C:/Users/20155/dpa4_project/data/jv_curve_test.png', 'rb') as f:
    img_base64 = base64.b64encode(f.read()).decode()

prompt = '这是一张钙钛矿太阳能电池的J-V曲线图。提取PCE、Voc、Jsc、FF数值。输出JSON格式：{"PCE": "值", "Voc": "值", "Jsc": "值", "FF": "值"}'

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

print("=== 原始响应 ===")
print(response)

print("\n=== 解析内容 ===")
content = response.output.choices[0].message.content
if isinstance(content, list):
    print(content[0].get('text', ''))
else:
    print(content)