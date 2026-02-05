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
        # 换用 gemini-flash-lite-latest (因为 Key 权限问题)
        model = genai.GenerativeModel('gemini-flash-lite-latest')
        init_error = None
    except Exception as e:
        init_error = str(e)
        print(f"Gemini Init Error: {e}")

# 加载本地知识库
KNOWLEDGE_FILE = "knowledge.json"
knowledge_base = []
if os.path.exists(KNOWLEDGE_FILE):
    try:
        with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
            knowledge_base = json.load(f)
        print(f"Loaded {len(knowledge_base)} records from knowledge base.")
    except Exception as e:
        print(f"Failed to load knowledge base: {e}")

def search_ragic(keyword):
    # 优先从本地知识库搜索
    if knowledge_base:
        results = []
        keyword = keyword.lower()
        for rec in knowledge_base:
            # 搜索问题和解决描述
            prob = rec.get("problem", "") 
            sol = rec.get("solution", "") 
            store = rec.get("store", "")
            model_name = rec.get("model", "")
            
            # 全方位搜索：问题、解决、店名、机型
            if (keyword in prob.lower() or 
                keyword in sol.lower() or 
                keyword in store.lower() or 
                keyword in model_name.lower()):
                
                mapped_rec = {
                    "發生問題": prob,
                    "處理紀錄": sol,
                    "機台型號": model_name,
                    "店家": store,  # 把店名也带上
                    "date": rec.get("date", "")
                }
                results.append(mapped_rec)
                
            # 限制返回数量 (比如只取前 20 条最相关的？这里是简单包含搜索)
            if len(results) >= 20:
                break
        return results

    # 如果本地没有，才去查 API (Fallback)
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
    角色：GAMA 公司的內部維修技術顧問。
    用戶提問："{user_query}"
    
    【任務】：
    請根據以下【歷史維修案例】來回答用戶。
    
    【嚴格規則】：
    1. **絕對禁止** 聯想到外部事物（例如：不要把 A4 當成奧迪汽車或紙張，它是店鋪代碼）。
    2. 你的知識邊界僅限於提供的這些案例。
    3. 如果案例裡沒有相關信息，請直接回答：「資料庫中暫無關於 '{user_query}' 的記錄。」
    4. 如果用戶問的是店家（如 A4），請總結該店家近期常發生的問題。
    
    【歷史案例】：
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
