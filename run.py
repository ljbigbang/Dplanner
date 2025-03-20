import sys
import os
import json
import asyncio
import websockets
from openai import OpenAI

DEEPSEEK_API_KEY = 'sk-c3b547b62c224059ba0cebfafc7a4f0a'
DEEPSEEK_URL = "https://api.deepseek.com"
async def chat(websocket):
    try:
        client = OpenAI(api_key=DEEPSEEK_API_KEY,base_url=DEEPSEEK_URL)
        await websocket.send("您好，有什么可以帮您的？")
        while True:
            user_input = await websocket.recv()
            response = client.chat.completions.create(
                model='deepseek-chat',
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": user_input},
                ],
                stream=False
            )
            await websocket.send(response.choices[0].message.content)
    except websockets.exceptions.ConnectionClosed:
        print("客户端主动断开连接")

async def plan(websocket):
    try:
        client = OpenAI(api_key=DEEPSEEK_API_KEY,base_url=DEEPSEEK_URL)
        await websocket.send("这是计划模块")
        while True:
            user_input = await websocket.recv()
            response = client.chat.completions.create(
                model='deepseek-chat',
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": user_input},
                ],
                stream=False
            )
            await websocket.send(response.choices[0].message.content)      
    except websockets.exceptions.ConnectionClosed:
        print("客户端主动断开连接")

async def handler(websocket):
    """处理每个 WebSocket 连接"""
    async for message in websocket:
        data = json.loads(message)
        if data['action'] == 'chat':
            await chat(websocket)
        elif data['action'] == 'plan':
            await plan(websocket)
    

async def main():
    port = int(os.getenv("PORT", 80))
    async with websockets.serve(
        handler,
        host="0.0.0.0",
        port=port,
        ping_interval=20
    ):
        print(f"服务已启动，监听端口 {port}")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
