from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
import requests
import google.generativeai as genai
import re
import json
import zipfile

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
        model = genai.GenerativeModel('gemini-flash-lite-latest')
        init_error = None
    except Exception as e:
        init_error = str(e)
        print(f"Gemini Init Error: {e}")

# 加载本地知识库 (ZIP 压缩版)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ZIP_FILE = os.path.join(BASE_DIR, "knowledge.zip")
JSON_FILE = "knowledge.json"
knowledge_base = []
kb_status = "Init"

try:
    if os.path.exists(ZIP_FILE):
        kb_status = "ZIP Found"
        with zipfile.ZipFile(ZIP_FILE, 'r') as zip_ref:
            zip_ref.extractall(BASE_DIR)
        kb_status = "Unzipped"
        
        json_path = os.path.join(BASE_DIR, JSON_FILE)
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8", errors="ignore") as f:
                knowledge_base = json.load(f)
            kb_status = f"Loaded ({len(knowledge_base)})"
        else:
            kb_status = "JSON Missing after unzip"
    else:
        kb_status = "ZIP Missing"
except Exception as e:
    kb_status = f"Error: {str(e)}"
    print(kb_status)

def search_ragic(user_query):
    # 优先从本地知识库搜索
    if knowledge_base:
        results = []
        user_query_upper = user_query.upper()
        
        # 1. 尝试提取店名
        target_store = None
        store_match = re.search(r'\b[A-Z][0-9]\b', user_query_upper)
        if store_match:
            target_store = store_match.group(0)
            user_query_upper = user_query_upper.replace(target_store, "").strip()
            
        # 2. 拆分剩余关键词
        keywords = user_query_upper.split()
        if not keywords and not target_store:
            return []
            
        for rec in knowledge_base:
            prob = str(rec.get("problem", ""))
            sol = str(rec.get("solution", ""))
            store = str(rec.get("store", ""))
            model_name = str(rec.get("model", ""))
            
            # A. 店名过滤
            if target_store and target_store != store.upper():
                continue 
                
            # B. 关键词匹配 (松散逻辑)
            full_text = (prob + sol + model_name).upper()
            match_count = 0
            for k in keywords:
                if k in full_text:
                    match_count += 1
            
            if (target_store and not keywords) or (match_count > 0):
                mapped_rec = {
                    "發生問題": prob,
                    "處理紀錄": sol,
                    "機台型號": model_name,
                    "店家": store,
                    "date": rec.get("date", ""),
                    "_score": match_count
                }
                results.append(mapped_rec)
                
        results.sort(key=lambda x: x["_score"], reverse=True)
        return results[:15]

    # Fallback to API
    try:
        params = {
            "api": "",
            "APIKey": RAGIC_API_KEY,
            "limit": 10,
            "listing": "1",
            "fts": user_query
        }
        resp = requests.get(RAGIC_URL, params=params)
        data = resp.json()
        if not data: return []
        return list(data.values()) if isinstance(data, dict) else data
    except:
        return []

def ask_ai_repair(user_query):
    records = search_ragic(user_query)
    
    if not records:
        context_text = "（数据库中未找到相关维修记录）"
    else:
        context_text = ""
        for i, rec in enumerate(records[:10]): 
            problem = rec.get("發生問題", "無描述")
            fix = rec.get("處理紀錄", "無記錄")
            model_name = rec.get("機台型號", "未知")
            store = rec.get("店家", "未知")
            context_text += f"案例{i+1}: 店家[{store}] 机型[{model_name}] 问题[{problem}] -> 处理[{fix}]\n"

    if not model:
        err = f"AI Error: {init_error}" if init_error else "AI Not Init"
        if records:
            return f"（{err}，KB: {kb_status}）\n{context_text}"
        else:
            return f"找不到相关记录。\n(KB Status: {kb_status})\n({err})"

    prompt = f"""
    角色：GAMA 公司的內部維修技術顧問。
    用戶提問："{user_query}"
    (Debug: KB Status={kb_status}, Matches={len(records)})
    
    【任務】：
    請根據以下【歷史維修案例】來回答用戶。
    
    【嚴格規則】：
    1. **絕對禁止** 聯想到外部事物（例如：不要把 A4 當成奧迪汽車或紙張，它是店鋪代碼）。
    2. 你的知識邊界僅限於提供的這些案例。
    3. 如果案例裡沒有相關信息，請直接回答：「資料庫中暫無關於 '{user_query}' 的記錄。(Matches: {len(records)})」
    4. 如果用戶問的是店家（如 A4），請總結該店家近期常發生的問題。
    
    【歷史案例】：
    {context_text}
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 思考時發生錯誤: {str(e)}"

@app.route("/", methods=['GET'])
def health_check():
    return f"LINE Bot (AI V4) is running! KB: {kb_status}"

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
    reply_text = ask_ai_repair(user_msg)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
