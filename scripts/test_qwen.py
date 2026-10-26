import dashscope
from dashscope import MultiModalConversation
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
dashscope.api_key = os.environ["DASHSCOPE_API_KEY"]
def test_qwen():
    try:
        response = MultiModalConversation.call(
            model="qwen-vl-plus",
            messages=[{
                "role": "user",
                "content": [
                    {"text": "请用中文描述这张图片的内容"},
                    {"image": "https://img.alicdn.com/imgextra/i4/O1CN01H4HCtF1RgBLpOAs6h_!!6000000002141-2-tps-817-556.png"}
                ]
            }]
        )
        print("✅ 请求成功")
        print(response)
    except Exception as e:
        print(f"❌ 失败: {e}")

if __name__ == "__main__":
    test_qwen()