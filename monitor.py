import os
import sys
import json
import time
from bs4 import BeautifulSoup
from curl_cffi import requests
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    PushMessageRequest,
    TextMessage
)

# 從環境變數讀取 LINE 金鑰（安全機制）
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID = os.getenv("LINE_USER_ID", "")
STATE_FILE = "stock_state.json"

def load_state():
    """讀取上一次的庫存狀態"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_state(state):
    """儲存當前庫存狀態"""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ 儲存狀態失敗: {e}")

def send_line_notification(store: str, title: str, url: str):
    """發送 LINE 補貨推播"""
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print("⚠️ 缺少 LINE 金鑰環境變數，略過推播")
        return

    msg_text = (
        f"🚨 【Owala 補貨通知！】\n\n"
        f"🏬 通路：{store}\n"
        f"📦 款式：{title}\n\n"
        f"👉 立即前往購買：\n{url}"
    )

    try:
        configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            push_request = PushMessageRequest(
                to=LINE_USER_ID,
                messages=[TextMessage(text=msg_text)]
            )
            line_bot_api.push_message(push_request)
        print("📲 LINE 補貨推播已成功送達你的手機！")
    except Exception as e:
        print(f"❌ LINE 推播失敗: {e}")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}

def check_finders_html(url: str):
    try:
        res = requests.get(url, headers=HEADERS, impersonate="chrome120", timeout=10)
        res.encoding = "utf-8"
        soup = BeautifulSoup(res.text, "html.parser")
        h1 = soup.find("h1")
        title = h1.text.strip() if h1 else "Owala 隨行杯"
        
        out_keywords = ["缺貨", "售完", "sold out", "暫無庫存", "補貨中"]
        has_out_keyword = any(kw in res.text.lower() for kw in out_keywords)
        
        if ("加入購物車" in res.text or "立即購買" in res.text) and not has_out_keyword:
            return True, title
        return False, title
    except Exception as e:
        print(f"  [Finders] 解析失敗: {e}")
    return False, "Owala 隨行杯"

def check_hola_html(url: str):
    try:
        res = requests.get(url, headers=HEADERS, impersonate="chrome120", timeout=10)
        res.encoding = "utf-8"
        soup = BeautifulSoup(res.text, "html.parser")
        title_tag = soup.title.string.strip() if soup.title else "HOLA Owala FreeSip"
        title = title_tag.split("｜")[0].strip()
        
        out_keywords = ["暫無庫存", "補貨中", "已售完", "缺貨中"]
        has_out_keyword = any(kw in res.text for kw in out_keywords)
        
        if "加入購物車" in res.text and not has_out_keyword:
            return True, title
        return False, title
    except Exception as e:
        print(f"  [HOLA] 解析失敗: {e}")
    return False, "HOLA Owala"

def check_eslite_html(url: str):
    try:
        res = requests.get(url, headers=HEADERS, impersonate="chrome120", timeout=10)
        res.encoding = "utf-8"
        soup = BeautifulSoup(res.text, "html.parser")
        h1 = soup.find("h1")
        title = h1.text.strip() if h1 else (soup.title.string.strip().split("-")[0].strip() if soup.title else "誠品 Owala")
        
        out_keywords = ["已售完", "暫無庫存", "補貨中", "缺貨中"]
        has_out_keyword = any(kw in res.text for kw in out_keywords)
        
        if ("放入購物車" in res.text or "立即結帳" in res.text) and not has_out_keyword:
            return True, title
        return False, title
    except Exception as e:
        print(f"  [誠品] 解析失敗: {e}")
    return False, "誠品 Owala"

# 監控商品目標清單（共 14 款）
TARGET_LIST = [
    # ==========================================
    # 1. Finders 通路
    # ==========================================
    {"store": "Finders (FreeSip 24oz)", "url": "https://www.finders.com.tw/products/owala-freesip-24oz", "checker": check_finders_html},
    {"store": "Finders (Tumbler 30oz)", "url": "https://www.finders.com.tw/products/owala-tumbler-30oz", "checker": check_finders_html},
    {"store": "Finders (Sway 30oz)", "url": "https://www.finders.com.tw/products/owala-sway-30oz", "checker": check_finders_html},

    # ==========================================
    # 2. HOLA 通路
    # ==========================================
    {"store": "HOLA (FreeSip 24oz)", "url": "https://www.hola.com.tw/p/014425080", "checker": check_hola_html},

    # ==========================================
    # 3. 誠品線上 - FreeSip 不鏽鋼保溫杯
    # ==========================================
    {"store": "誠品 (不鏽鋼-冰河白)", "url": "https://www.eslite.com/product/10052271402683070020000", "checker": check_eslite_html},
    {"store": "誠品 (不鏽鋼-繽紛雪酪)", "url": "https://www.eslite.com/product/10052271402683070019004", "checker": check_eslite_html},
    {"store": "誠品 (不鏽鋼-極夜黑)", "url": "https://www.eslite.com/product/10052271402683070017000", "checker": check_eslite_html},
    {"store": "誠品 (不鏽鋼-沙丘棕)", "url": "https://www.eslite.com/product/10052271402683051103005", "checker": check_eslite_html},
    {"store": "誠品 (不鏽鋼-雙飲款式)", "url": "https://www.eslite.com/product/10052271402683051105009", "checker": check_eslite_html},

    # ==========================================
    # 4. 誠品線上 - FreeSip Tritan 透明款
    # ==========================================
    {"store": "誠品 (Tritan 款式1)", "url": "https://www.eslite.com/product/1005477542682299958002", "checker": check_eslite_html},
    {"store": "誠品 (Tritan 款式2)", "url": "https://www.eslite.com/product/10052271402683055269004", "checker": check_eslite_html},

    # ==========================================
    # 5. 誠品線上 - FreeSip Sway 系列
    # ==========================================
    {"store": "誠品 (Sway 款式1)", "url": "https://www.eslite.com/product/10052271402683097131000", "checker": check_eslite_html},
    {"store": "誠品 (Sway 款式2)", "url": "https://www.eslite.com/product/10052271402683097106008", "checker": check_eslite_html},
    {"store": "誠品 (Sway 款式3)", "url": "https://www.eslite.com/product/10052271402683097107005", "checker": check_eslite_html},
]

def main():
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] 🚀 執行單輪庫存掃描...")

    
    prev_state = load_state()
    curr_state = {}
    
    for item in TARGET_LIST:
        store = item["store"]
        url = item["url"]
        checker = item["checker"]
        
        in_stock, product_name = checker(url)
        curr_state[url] = in_stock
        was_in_stock = prev_state.get(url, False)
        
        if in_stock:
            if not was_in_stock:
                print(f"🎉 [{store}] 新補貨上架！發送 LINE 通知: {product_name}")
                send_line_notification(store, product_name, url)
            else:
                print(f"  ✨ [{store}] 依然有貨（已通知過）- {product_name}")
        else:
            print(f"  💤 [{store}] 缺貨中 - {product_name}")
            
        time.sleep(1)
        
    save_state(curr_state)
    print(f"[{now}] ✅ 掃描完成並更新狀態檔！")

if __name__ == "__main__":
    main()
