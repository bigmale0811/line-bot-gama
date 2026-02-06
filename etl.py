import requests
import json
import re
import os
import zipfile
from datetime import datetime

# 配置 (从环境变量读取)
API_KEY = os.environ.get("RAGIC_API_KEY")
if not API_KEY:
    print("Error: RAGIC_API_KEY not found in env.")
    exit(1)

BASE_URL = "https://ap15.ragic.com/GB2/forms3/1"
OUTPUT_JSON = "knowledge.json"
OUTPUT_ZIP = "knowledge.zip"

# 设定起始日期：2025年1月1日
CUTOFF_DATE = datetime(2025, 1, 1)
print(f"[INFO] Start Date: {CUTOFF_DATE.strftime('%Y-%m-%d')}")

# 字段映射
FIELD_MAP = {
    "單號": "id",
    "發生時間": "date",
    "店家": "store",
    "機台型號": "model",
    "發生問題": "problem", 
    "處理紀錄": "solution"   
}

def clean_text(text):
    if not text: return ""
    text = str(text)
    text = text.replace("[br]", "\n")
    text = re.sub(r'<[^>]+>', '', text)
    return text.strip()

def fetch_and_clean():
    all_clean_records = []
    offset = 0
    limit = 1000
    has_more = True
    
    print("Starting ETL process...")

    while has_more:
        print(f"Fetching offset {offset}...")
        
        try:
            params = {
                "api": "",
                "APIKey": API_KEY,
                "limit": limit,
                "offset": offset,
                "listing": "1",
                "order": "DESC" # 尝试让它倒序 (最新在前) 抓取，看能不能抓到最新的
            }
            
            response = requests.get(BASE_URL, params=params, timeout=30)
            if response.status_code != 200:
                print(f"API Error: {response.status_code}")
                break
                
            data = response.json()
            if not data: break

            records = list(data.values()) if isinstance(data, dict) else data
            if len(records) == 0: break

            batch_processed = 0

            for record in records:
                # 1. 检查时间
                raw_date = record.get("發生時間", "")
                try:
                    if raw_date:
                        record_date = datetime.strptime(raw_date, "%Y/%m/%d %H:%M:%S")
                        if record_date < CUTOFF_DATE:
                            continue
                except:
                    pass

                # 2. 提取并清洗
                clean_entry = {}
                has_content = False
                is_admin_task = False 

                for ragic_key, my_key in FIELD_MAP.items():
                    raw_val = record.get(ragic_key, "")
                    cleaned_val = clean_text(raw_val)
                    clean_entry[my_key] = cleaned_val
                    
                    if my_key == "model" and "庶務工作" in cleaned_val:
                        is_admin_task = True
                    if my_key in ["problem", "solution"] and cleaned_val:
                        has_content = True
                
                # 3. 过滤
                if has_content and not is_admin_task:
                    all_clean_records.append(clean_entry)
                    batch_processed += 1

            print(f"   Processed batch: {batch_processed}")
            offset += limit
            
            # 安全限制：防止GitHub Action超时，设为 50000
            if offset > 50000: 
                print("WARNING: Safety limit reached.")
                break
                
        except Exception as e:
            print(f"Exception: {e}")
            break

    # 保存 JSON
    print(f"Saving {len(all_clean_records)} records to JSON...")
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(all_clean_records, f, ensure_ascii=False, indent=2)
        
    # 压缩为 ZIP
    print(f"Compressing to {OUTPUT_ZIP}...")
    with zipfile.ZipFile(OUTPUT_ZIP, 'w', zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(OUTPUT_JSON)
    
    # 删除原始 JSON (节省空间)
    os.remove(OUTPUT_JSON)
    
    print(f"DONE! {OUTPUT_ZIP} is ready.")

if __name__ == "__main__":
    fetch_and_clean()
