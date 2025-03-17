# 创建应用实例
import sys
from flask import Flask, request, jsonify
import requests
# from wxcloudrun import app
app = Flask(__name__)


# 启动Flask Web服务
if __name__ == '__main__':
    app.run(host=sys.argv[1], port=sys.argv[2])
