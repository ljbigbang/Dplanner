import sys
from flask import Flask, request, jsonify
from openai import OpenAI

DEEPSEEK_API_KEY = 'sk-c3b547b62c224059ba0cebfafc7a4f0a'
DEEPSEEK_URL = "https://api.deepseek.com"
app = Flask(__name__)

@app.route('/chat', methods=['POST'])
def chat():
    # 参数校验
    user_input = request.json.get('content')
    if not user_input:
        return jsonify({"code":400, "error":"Empty message"}), 400
    
    # 调用DeepSeek API
    try:
        client = OpenAI(api_key=DEEPSEEK_API_KEY,base_url=DEEPSEEK_URL)
        response = client.chat.completions.create(
            model='deepseek-chat',
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": user_input},
            ],
            stream=False
        )
        return jsonify({
            "code":200, 
            "reply":response.choices[0].message.content
        })
    except Exception as e:
        return jsonify({"code":500, "error":str(e)}), 500

# 启动Flask Web服务
if __name__ == '__main__':
    app.run(host=sys.argv[1], port=sys.argv[2])
