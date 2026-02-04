from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
import json
import requests

app = Flask(__name__)

# 从环境变量获取 Key (更安全)
CHANNEL_ACCESS_TOKEN = os.environ.get('CHANNEL_ACCESS_TOKEN')
CHANNEL_SECRET = os.environ.get('CHANNEL_SECRET')

# 如果环境变量没设，使用默认值 (不推荐，但为了测试方便)
if not CHANNEL_ACCESS_TOKEN:
    CHANNEL_ACCESS_TOKEN = "tYE9WVIdynVTljAKPDw9532e0/gR1kwT9YXtWwqn4fQHKFkbZgznX1mBxKBBANbAgpOVT0TX3fkihBpNm/86kPOB7bwqrs7rkLYRGJSHa9/PxrURmxpmBw8ZLo/2AO6HjfozGh1G9GqwtJaBafcWIgdB04t89/1O/w1cDnyilFU="
if not CHANNEL_SECRET:
    CHANNEL_SECRET = "a4791a0f8a5c3f02748f99f990b3ba1f"

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# Ragic 配置
RAGIC_API_KEY = os.environ.get('RAGIC_API_KEY', "ZnNEUjI3UlI1UFYrVmIxS3BPSUU3MnJBbEJuVDg4c2R5WFd3WXd3b2ZkOTdSZ1ZKWGNxL0xRb2ZUTi9CZDcyVQ==")
RAGIC_URL = "https://ap15.ragic.com/GB2/forms3/1"

def search_ragic(keyword):
    """简单的 Ragic 搜索功能"""
    try:
        params = {
            "api": "",
            "APIKey": RAGIC_API_KEY,
            "limit": 5, # 只找前5条
            "listing": "1"
        }
        # 这里应该加上 full text search 参数，Ragic 是 fts
        params["fts"] = keyword
        
        resp = requests.get(RAGIC_URL, params=params)
        data = resp.json()
        
        if not data:
            return "找不到相關維修記錄。"
            
        records = list(data.values()) if isinstance(data, dict) else data
        if not records:
            return "找不到相關維修記錄。"
            
        result_text = f"🔍 找到 {len(records)} 筆關於「{keyword}」的記錄：\n"
        for i, rec in enumerate(records[:3]): # 只顯示前3條
            problem = rec.get("發生問題", "無描述")
            fix = rec.get("處理紀錄", "無記錄")
            result_text += f"\n{i+1}. 🔴 {problem}\n   🟢 {fix}\n"
            
        return result_text
        
    except Exception as e:
        return f"查询出错: {str(e)}"

@app.route("/", methods=['GET'])
def health_check():
    return "LINE Bot is running!"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text.strip()
    print(f"收到: {user_msg}")
    
    reply_text = ""
    
    # 关键词触发查询
    if user_msg.startswith("查 ") or user_msg.startswith("查询 "):
        keyword = user_msg.split(" ", 1)[1]
        reply_text = search_ragic(keyword)
    elif "壞" in user_msg or "故障" in user_msg or "error" in user_msg.lower():
         # 模糊触发
         reply_text = search_ragic(user_msg)
    else:
        # 默认回声 (或者你可以改成由 AI 处理)
        reply_text = f"收到: {user_msg}\n(輸入「查 關鍵字」可以搜尋維修庫)"
        
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
