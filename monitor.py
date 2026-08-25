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

# 從環境變數讀取 LINE 金鑰
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID = os.getenv("LINE_USER_ID", "")
STATE_FILE = "stock_state.json"

# 指定監控的誠品實體門市清單
TARGET_ESLITE_STORES = ["新店", "南西", "台大", "站前"]

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
        f"🏬 通路/門市：{store}\n"
        f"📦 款式：{title}\n\n"
        f"👉 點擊查看詳情/購買：\n{url}"
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

def check_eslite_online_html(url: str):
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
        print(f"  [誠品線上] 解析失敗: {e}")
    return False, "誠品 Owala"

def check_eslite_store_stock(url: str, target_stores: list = TARGET_ESLITE_STORES):
    """查詢誠品實體門市庫存 API"""
    try:
        # 從網址解析出商品 ID
        product_id = url.rstrip("/").split("/")[-1]
        api_url = f"https://athena.eslite.com/api/v1/products/{product_id}/stores"
        
        res = requests.get(api_url, headers=HEADERS, impersonate="chrome120", timeout=10)
        if res.status_code != 200:
            return False, "門市查詢異常"
        
        data = res.json()
        in_stock_stores = []
        product_name = data.get("name", "Owala 保溫杯")
        
        # 遍歷各區域門市
        for region in data.get("regions", []):
            for store in region.get("stores", []):
                store_name = store.get("name", "")
                stock_desc = store.get("stock_status", "") or store.get("stock_desc", "")
                
                # 判斷是否為指定關注門市
                if any(target in store_name for target in target_stores):
                    # 狀態不含「無庫存」且不含「電洽」即視為有貨
                    if "無庫存" not in stock_desc and "需購請電洽" not in stock_desc and stock_desc != "":
                        in_stock_stores.append(f"{store_name} ({stock_desc})")
        
        if in_stock_stores:
            detail_info = f"{product_name} ➔ 【{'、'.join(in_stock_stores)}】"
            return True, detail_info
        return False, product_name
    except Exception as e:
        print(f"  [誠品實體門市] 查詢失敗: {e}")
    return False, "誠品實體門市"

# 監控清單（線上商城 + 指定門市實體庫存）
TARGET_LIST = [
    # ------------------ Finders 通路 ------------------
    {"store": "Finders (FreeSip 24oz)", "url": "https://www.finders.com.tw/products/owala-freesip-24oz", "checker": check_finders_html},
    {"store": "Finders (Tumbler 30oz)", "url": "https://www.finders.com.tw/products/owala-tumbler-30oz", "checker": check_finders_html},
    {"store": "Finders (Sway 30oz)", "url": "https://www.finders.com.tw/products/owala-sway-30oz", "checker": check_finders_html},

    # ------------------ HOLA 通路 ------------------
    {"store": "HOLA (FreeSip 24oz)", "url": "https://www.hola.com.tw/p/014425080", "checker": check_hola_html},

    # ------------------ 誠品線上商城 ------------------
    {"store": "誠品線上 (不鏽鋼-冰河白)", "url": "https://www.eslite.com/product/10052271402683070020000", "checker": check_eslite_online_html},
    {"store": "誠品線上 (不鏽鋼-繽紛雪酪)", "url": "https://www.eslite.com/product/10052271402683070019004", "checker": check_eslite_online_html},
    {"store": "誠品線上 (不鏽鋼-極夜黑)", "url": "https://www.eslite.com/product/10052271402683070017000", "checker": check_eslite_online_html},
    {"store": "誠品線上 (不鏽鋼-沙丘棕)", "url": "https://www.eslite.com/product/10052271402683051103005", "checker": check_eslite_online_html},
    {"store": "誠品線上 (不鏽鋼-雙飲款)", "url": "https://www.eslite.com/product/10052271402683051105009", "checker": check_eslite_online_html},
    {"store": "誠品線上 (Tritan 款式1)", "url": "https://www.eslite.com/product/1005477542682299958002", "checker": check_eslite_online_html},
    {"store": "誠品線上 (Tritan 款式2)", "url": "https://www.eslite.com/product/10052271402683055269004", "checker": check_eslite_online_html},
    {"store": "誠品線上 (Sway 款式1)", "url": "https://www.eslite.com/product/10052271402683097131000", "checker": check_eslite_online_html},
    {"store": "誠品線上 (Sway 款式2)", "url": "https://www.eslite.com/product/10052271402683097106008", "checker": check_eslite_online_html},
    {"store": "誠品線上 (Sway 款式3)", "url": "https://www.eslite.com/product/10052271402683097107005", "checker": check_eslite_online_html},

    # ------------------ 誠品實體門市（新店 / 南西 / 台大 / 站前）------------------
    {"store": "誠品門市 (不鏽鋼-冰河白)", "url": "https://www.eslite.com/product/10052271402683070020000", "checker": check_eslite_store_stock},
    {"store": "誠品門市 (不鏽鋼-繽紛雪酪)", "url": "https://www.eslite.com/product/10052271402683070019004", "checker": check_eslite_store_stock},
    {"store": "誠品門市 (不鏽鋼-極夜黑)", "url": "https://www.eslite.com/product/10052271402683070017000", "checker": check_eslite_store_stock},
    {"store": "誠品門市 (不鏽鋼-沙丘棕)", "url": "https://www.eslite.com/product/10052271402683051103005", "checker": check_eslite_store_stock},
    {"store": "誠品門市 (不鏽鋼-雙飲款)", "url": "https://www.eslite.com/product/10052271402683051105009", "checker": check_eslite_store_stock},
    {"store": "誠品門市 (Tritan 款式1)", "url": "https://www.eslite.com/product/1005477542682299958002", "checker": check_eslite_store_stock},
    {"store": "誠品門市 (Tritan 款式2)", "url": "https://www.eslite.com/product/10052271402683055269004", "checker": check_eslite_store_stock},
    {"store": "誠品門市 (Sway 款式1)", "url": "https://www.eslite.com/product/10052271402683097131000", "checker": check_eslite_store_stock},
    {"store": "誠品門市 (Sway 款式2)", "url": "https://www.eslite.com/product/10052271402683097106008", "checker": check_eslite_store_stock},
    {"store": "誠品門市 (Sway 款式3)", "url": "https://www.eslite.com/product/10052271402683097107005", "checker": check_eslite_store_stock},
]

def main():
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] 🚀 執行線上與實體門市庫存掃描...")
    
    prev_state = load_state()
    curr_state = {}
    
    for item in TARGET_LIST:
        store = item["store"]
        url = item["url"]
        checker = item["checker"]
        
        # 區分線上與實體的 state key 避免覆蓋
        state_key = f"{store}::{url}"
        
        in_stock, product_name = checker(url)
        curr_state[state_key] = in_stock
        was_in_stock = prev_state.get(state_key, False)
        
        if in_stock:
            if not was_in_stock:
                print(f"🎉 [{store}] 補貨上架！發送 LINE 通知: {product_name}")
                send_line_notification(store, product_name, url)
            else:
                print(f"  ✨ [{store}] 依然有貨（已通知過）- {product_name}")
        else:
            print(f"  💤 [{store}] 缺貨中 - {product_name}")
            
        time.sleep(0.5)
        
    save_state(curr_state)
    print(f"[{now}] ✅ 線上與實體門市掃描完成並更新狀態檔！")

if __name__ == "__main__":
    main()
