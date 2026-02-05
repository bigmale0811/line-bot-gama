from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
import requests
import google.generativeai as genai

app = Flask(__name__)

# 配置
CHANNEL_ACCESS_TOKEN = os.environ.get('CHANNEL_ACCESS_TOKEN')
CHANNEL_SECRET = os.environ.get('CHANNEL_SECRET')
RAGIC_API_KEY = os.environ.get('RAGIC_API_KEY')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
RAGIC_URL = "https://ap15.ragic.com/GB2/forms3/1"

# 初始化 Line
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# 初始化 Gemini
model = None
init_error = "No Key"
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        # 换回 gemini-pro (1.0) 试试
        model = genai.GenerativeModel('gemini-pro')
        init_error = None
    except Exception as e:
        init_error = str(e)
        print(f"Gemini Init Error: {e}")

def search_ragic(keyword):
    try:
        params = {
            "api": "",
            "APIKey": RAGIC_API_KEY,
            "limit": 10, # 多抓几条给 AI 分析
            "listing": "1",
            "fts": keyword
        }
        resp = requests.get(RAGIC_URL, params=params)
        data = resp.json()
        
        if not data:
            return []
        return list(data.values()) if isinstance(data, dict) else data
    except:
        return []

def ask_ai_repair(user_query):
    # 1. 先去 Ragic 找相关资料
    records = search_ragic(user_query)
    
    # 2. 整理资料给 AI
    if not records:
        context_text = "（数据库中未找到相关维修记录）"
    else:
        context_text = ""
        for i, rec in enumerate(records[:5]): 
            problem = rec.get("發生問題", "無描述")
            fix = rec.get("處理紀錄", "無記錄")
            model_name = rec.get("機台型號", "未知")
            context_text += f"案例{i+1}: 机型[{model_name}] 问题[{problem}] -> 处理[{fix}]\n"

    # 如果 AI 没初始化，直接返回原始数据 + 错误信息
    if not model:
        err = f"AI Error: {init_error}" if init_error else "AI Not Init"
        if records:
            return f"（{err}，顯示原始记录）\n{context_text}"
        else:
            return f"找不到相关记录。({err})"

    # 3. 让 AI 思考
    prompt = f"""
    你是一个资深的维修技术顾问。用户遇到了这个问题："{user_query}"
    
    请根据以下【公司历史维修案例】来回答。
    
    【规则】：
    1. 如果有历史案例，请总结案例中的解决方法，并注明“根据历史记录...”。
    2. 如果没有历史案例（或案例不相关），请运用你的通用维修知识给出建议，并注明“数据库中暂无此类记录，建议...”。
    3. 如果用户只是在打招呼（如你好、早安），请友善回复，不要强行解释故障。
    4. 回答要简练、专业、有条理。
    
    【历史案例】：
    {context_text}
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 思考時發生錯誤: {str(e)}\n\n但我找到了 {len(records)} 條相關記錄，您可以手動查詢。"

@app.route("/", methods=['GET'])
def health_check():
    return "LINE Bot (AI V2) is running!"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text.strip()
    print(f"收到: {user_msg}")
    
    # 不再需要 "查" 字，直接当成问题处理
    # 为了避免閒聊也触发查询，可以设置一个简单的过滤器，或者全部都回
    # 这里设置为：全部尝试 AI 回答
    
    reply_text = ask_ai_repair(user_msg)
        
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
