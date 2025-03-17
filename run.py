# 创建应用实例
import sys
from flask import Flask, request, jsonify
import requests
import os
# from wxcloudrun import app
app = Flask(__name__)
DEEPSEEK_API_KEY = os.getenv('sk-c3b547b62c224059ba0cebfafc7a4f0a')
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

@app.route('/chat', methods=['POST'])
def chat():
    # 参数校验
    user_input = request.json.get('content')
    if not user_input:
        return jsonify({"code":400, "error":"Empty message"}), 400
    
    # 调用DeepSeek API
    headers = {
        "Authorization": `Bearer ${DEEPSEEK_API_KEY}`,
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": user_input}],
        "temperature": 0.7
    }
    
    try:
        response = requests.post(DEEPSEEK_URL, json=payload, headers=headers)
        response.raise_for_status()
        return jsonify({
            "code":200,
            "reply": response.json()['choices'][0]['message']['content']
        })
    except Exception as e:
        return jsonify({"code":500, "error":str(e)}), 500

# 启动Flask Web服务
if __name__ == '__main__':
    app.run(host=sys.argv[1], port=sys.argv[2])
