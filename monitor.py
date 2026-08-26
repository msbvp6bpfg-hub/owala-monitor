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

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID = os.getenv("LINE_USER_ID", "")
STATE_FILE = "stock_state.json"

TARGET_ESLITE_STORES = ["新店", "南西", "台大", "站前"]

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ 儲存狀態失敗: {e}")

def send_line_notification(store: str, title: str, url: str):
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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}

def check_finders(url: str):
    try:
        res = requests.get(url, headers=HEADERS, impersonate="chrome120", timeout=12)
        res.encoding = "utf-8"
        soup = BeautifulSoup(res.text, "html.parser")
        h1 = soup.find("h1")
        title = h1.text.strip() if h1 else "Owala 隨行杯"
        
        out_keywords = ["缺貨", "售完", "sold out", "暫無庫存", "補貨中"]
        has_out = any(kw in res.text.lower() for kw in out_keywords)
        
        if ("加入購物車" in res.text or "立即購買" in res.text) and not has_out:
            return True, title
        return False, title
    except Exception as e:
        return False, "Owala 隨行杯"

def check_hola(url: str):
    try:
        res = requests.get(url, headers=HEADERS, impersonate="chrome120", timeout=12)
        res.encoding = "utf-8"
        soup = BeautifulSoup(res.text, "html.parser")
        title_tag = soup.title.string.strip() if soup.title else "HOLA Owala FreeSip"
        title = title_tag.split("｜")[0].strip()
        
        out_keywords = ["暫無庫存", "補貨中", "已售完", "缺貨中"]
        has_out = any(kw in res.text for kw in out_keywords)
        
        if "加入購物車" in res.text and not has_out:
            return True, title
        return False, title
    except Exception as e:
        return False, "HOLA Owala"

def check_eslite_combined(item_name: str, url: str):
    """一箭雙鵰：一次請求同時檢查誠品線上與實體門市庫存"""
    online_stock = False
    store_stock = False
    online_title = item_name
    store_title = "實體門市無庫存"
    
    try:
        res = requests.get(url, headers=HEADERS, impersonate="chrome120", timeout=12)
        if res.status_code == 200 and "Sorry, you have been blocked" not in res.text:
            soup = BeautifulSoup(res.text, "html.parser")
            h1 = soup.find("h1")
            online_title = h1.text.strip() if h1 else item_name
            
            # 1. 檢查線上庫存
            out_keywords = ["已售完", "暫無庫存", "補貨中", "缺貨中"]
            has_out = any(kw in res.text for kw in out_keywords)
            if ("放入購物車" in res.text or "立即結帳" in res.text) and not has_out:
                online_stock = True

            # 2. 檢查實體門市庫存
            product_id = url.rstrip("/").split("/")[-1]
            api_url = f"https://athena.eslite.com/api/v1/products/{product_id}/stores"
            api_res = requests.get(api_url, headers=HEADERS, impersonate="chrome120", timeout=12)
            
            if api_res.status_code == 200:
                data = api_res.json()
                in_stock_stores = []
                regions = data.get("regions") or data.get("data", {}).get("regions", []) or []
                for region in regions:
                    for store in region.get("stores", []):
                        s_name = store.get("name", "")
                        s_desc = store.get("stock_status") or store.get("stock_desc") or ""
                        if any(target in s_name for target in TARGET_ESLITE_STORES):
                            if s_desc and "無庫存" not in s_desc and "電洽" not in s_desc:
                                in_stock_stores.append(f"{s_name}({s_desc})")
                
                if in_stock_stores:
                    store_stock = True
                    store_title = f"{online_title} ➔ 【{'、'.join(in_stock_stores)}】"
    except Exception as e:
        pass
        
    return online_stock, online_title, store_stock, store_title

# 監控目標清單
FINDERS_HOLA_LIST = [
    {"store": "Finders (FreeSip 24oz)", "url": "https://www.finders.com.tw/products/owala-freesip-24oz", "checker": check_finders},
    {"store": "Finders (Tumbler 30oz)", "url": "https://www.finders.com.tw/products/owala-tumbler-30oz", "checker": check_finders},
    {"store": "Finders (Sway 30oz)", "url": "https://www.finders.com.tw/products/owala-sway-30oz", "checker": check_finders},
    {"store": "HOLA (FreeSip 24oz)", "url": "https://www.hola.com.tw/p/014425080", "checker": check_hola},
]

ESLITE_LIST = [
    {"name": "誠品 (不鏽鋼-冰河白)", "url": "https://www.eslite.com/product/10052271402683070020000"},
    {"name": "誠品 (不鏽鋼-繽紛雪酪)", "url": "https://www.eslite.com/product/10052271402683070019004"},
    {"name": "誠品 (不鏽鋼-極夜黑)", "url": "https://www.eslite.com/product/10052271402683070017000"},
    {"name": "誠品 (不鏽鋼-沙丘棕)", "url": "https://www.eslite.com/product/10052271402683051103005"},
    {"name": "誠品 (不鏽鋼-雙飲款)", "url": "https://www.eslite.com/product/10052271402683051105009"},
    {"name": "誠品 (Tritan 款式1)", "url": "https://www.eslite.com/product/1005477542682299958002"},
    {"name": "誠品 (Tritan 款式2)", "url": "https://www.eslite.com/product/10052271402683055269004"},
    {"name": "誠品 (Sway 款式1)", "url": "https://www.eslite.com/product/10052271402683097131000"},
    {"name": "誠品 (Sway 款式2)", "url": "https://www.eslite.com/product/10052271402683097106008"},
    {"name": "誠品 (Sway 款式3)", "url": "https://www.eslite.com/product/10052271402683097107005"},
]

def main():
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] 🚀 執行線上與實體門市庫存掃描...")
    
    prev_state = load_state()
    curr_state = {}
    
    # 1. 檢查 Finders & HOLA
    for item in FINDERS_HOLA_LIST:
        store = item["store"]
        url = item["url"]
        in_stock, title = item["checker"](url)
        curr_state[url] = in_stock
        
        if in_stock:
            if not prev_state.get(url, False):
                print(f"🎉 [{store}] 補貨上架！發送 LINE 通知: {title}")
                send_line_notification(store, title, url)
            else:
                print(f"  ✨ [{store}] 依然有貨 - {title}")
        else:
            print(f"  💤 [{store}] 缺貨中 - {title}")
        time.sleep(1)
        
    # 2. 檢查 誠品 (線上 + 門市)
    for item in ESLITE_LIST:
        name = item["name"]
        url = item["url"]
        
        online_stock, online_title, store_stock, store_title = check_eslite_combined(name, url)
        
        # 處理線上狀態
        online_key = f"{url}#online"
        curr_state[online_key] = online_stock
        if online_stock:
            if not prev_state.get(online_key, False):
                print(f"🎉 [誠品線上] 補貨上架！發送 LINE 通知: {online_title}")
                send_line_notification("誠品線上商城", online_title, url)
            else:
                print(f"  ✨ [誠品線上] 依然有貨 - {online_title}")
        else:
            print(f"  💤 [{name} 線上] 缺貨中")

        # 處理門市狀態
        store_key = f"{url}#store"
        curr_state[store_key] = store_stock
        if store_stock:
            if not prev_state.get(store_key, False):
                print(f"🎉 [誠品門市] 門市有貨！發送 LINE 通知: {store_title}")
                send_line_notification("誠品實體門市", store_title, url)
            else:
                print(f"  ✨ [誠品門市] 依然有貨 - {store_title}")
        else:
            print(f"  💤 [{name} 門市] 缺貨中")
            
        time.sleep(1.5)
        
    save_state(curr_state)
    print(f"[{now}] ✅ 線上與實體門市掃描完成！")

if __name__ == "__main__":
    main()
