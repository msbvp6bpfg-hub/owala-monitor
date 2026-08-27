import os
import sys
import json
import time
import re
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

def send_line_notification(store: str, title: str, url: str, is_instant_checkout: bool = False):
    """發送 LINE 推播（支援一般通知與極速一鍵結帳通知）"""
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print("⚠️ 缺少 LINE 金鑰環境變數，略過推播")
        return

    if is_instant_checkout:
        msg_text = (
            f"⚡ 【Owala 補貨 - 一鍵直通結帳！】\n\n"
            f"🏬 通路：{store}\n"
            f"📦 鎖定款式：{title}\n\n"
            f"🔥 點擊直接進結帳頁（已自動加購物車）：\n{url}\n\n"
            f"💡 提示：點入後直接按快速支付即完成下單！"
        )
    else:
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
        print(f"📲 LINE {'一鍵結帳' if is_instant_checkout else '一般'}推播已送達！")
    except Exception as e:
        print(f"❌ LINE 推播失敗: {e}")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}

def check_finders_detailed(url: str):
    """
    專門解析 Finders 規格：
    若晶鑽黑有貨，產生一鍵直通結帳連結；其餘顏色有貨則回傳普通頁面。
    """
    try:
        res = requests.get(url, headers=HEADERS, impersonate="chrome120", timeout=12)
        res.encoding = "utf-8"
        text = res.text
        
        # 尋找 Shopline 前端規格 JSON 數據
        variations = []
        var_match = re.search(r'variations\s*:\s*(\[\{.*?\}\])\s*,', text, re.DOTALL)
        if var_match:
            try:
                variations = json.loads(var_match.group(1))
            except Exception:
                pass

        black_in_stock = False
        black_checkout_url = ""
        other_in_stock = False
        other_titles = []

        if variations:
            for v in variations:
                v_id = v.get("_id") or v.get("id", "")
                fields = v.get("fields", [])
                v_title = " / ".join([f.get("value", "") for f in fields])
                is_available = v.get("is_preorder", False) or (v.get("quantity", 0) > 0)
                
                if "晶鑽黑" in v_title or "Black" in v_title:
                    if is_available:
                        black_in_stock = True
                        # Shopline 一鍵加購直通結帳網址
                        black_checkout_url = f"https://www.finders.com.tw/cart?variant_id={v_id}&quantity=1"
                else:
                    if is_available:
                        other_in_stock = True
                        other_titles.append(v_title)
        else:
            # 備用解析方式
            out_keywords = ["缺貨", "售完", "sold out", "暫無庫存", "補貨中"]
            has_out = any(kw in text.lower() for kw in out_keywords)
            if ("加入購物車" in text or "立即購買" in text) and not has_out:
                other_in_stock = True
                other_titles.append("全款式庫存開放")

        return {
            "black_in_stock": black_in_stock,
            "black_checkout_url": black_checkout_url or f"https://www.finders.com.tw/cart/add?url={url}",
            "other_in_stock": other_in_stock,
            "other_title": "、".join(other_titles) if other_titles else "其他顏色"
        }
    except Exception as e:
        print(f"  [Finders FreeSip] 解析略過: {e}")
        return {"black_in_stock": False, "black_checkout_url": "", "other_in_stock": False, "other_title": ""}

def check_finders_general(url: str):
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
    except Exception:
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
    except Exception:
        return False, "HOLA Owala"

def check_eslite_combined(item_name: str, url: str):
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
    except Exception:
        pass
        
    return online_stock, online_title, store_stock, store_title

# 監控清單
OTHER_FINDERS_HOLA_LIST = [
    {"store": "Finders (Tumbler 30oz)", "url": "https://www.finders.com.tw/products/owala-tumbler-30oz", "checker": check_finders_general},
    {"store": "Finders (Sway 30oz)", "url": "https://www.finders.com.tw/products/owala-sway-30oz", "checker": check_finders_general},
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

    # 1. 專屬檢查：Finders FreeSip 24oz（區分晶鑽黑直通結帳 vs 其他顏色）
    freesip_url = "https://www.finders.com.tw/products/owala-freesip-24oz"
    finders_result = check_finders_detailed(freesip_url)
    
    # 晶鑽黑狀態處理
    black_key = f"{freesip_url}#black_checkout"
    curr_state[black_key] = finders_result["black_in_stock"]
    if finders_result["black_in_stock"]:
        if not prev_state.get(black_key, False):
            print(f"🔥 [Finders] 晶鑽黑補貨！發送【一鍵直通結帳】LINE 通知！")
            send_line_notification("Finders 官方", "Owala FreeSip 24oz (晶鑽黑)", finders_result["black_checkout_url"], is_instant_checkout=True)
        else:
            print("  ✨ [Finders] 晶鑽黑依然有貨（已通知過）")
    else:
        print("  💤 [Finders] 晶鑽黑 缺貨中")

    # 其他顏色狀態處理
    other_key = f"{freesip_url}#others"
    curr_state[other_key] = finders_result["other_in_stock"]
    if finders_result["other_in_stock"]:
        if not prev_state.get(other_key, False):
            print(f"🎉 [Finders] 其他顏色補貨！發送一般通知")
            send_line_notification("Finders 官方", f"Owala FreeSip 24oz ({finders_result['other_title']})", freesip_url, is_instant_checkout=False)
        else:
            print(f"  ✨ [Finders] 其他顏色依然有貨 - {finders_result['other_title']}")
    else:
        print("  💤 [Finders FreeSip] 其他顏色 缺貨中")
    
    time.sleep(1)

    # 2. 檢查其他 Finders & HOLA
    for item in OTHER_FINDERS_HOLA_LIST:
        store = item["store"]
        url = item["url"]
        in_stock, title = item["checker"](url)
        curr_state[url] = in_stock
        
        if in_stock:
            if not prev_state.get(url, False):
                print(f"🎉 [{store}] 補貨上架！發送 LINE 通知: {title}")
                send_line_notification(store, title, url, is_instant_checkout=False)
            else:
                print(f"  ✨ [{store}] 依然有貨 - {title}")
        else:
            print(f"  💤 [{store}] 缺貨中 - {title}")
        time.sleep(1)
        
    # 3. 檢查 誠品 (線上 + 實體門市)
    for item in ESLITE_LIST:
        name = item["name"]
        url = item["url"]
        online_stock, online_title, store_stock, store_title = check_eslite_combined(name, url)
        
        online_key = f"{url}#online"
        curr_state[online_key] = online_stock
        if online_stock:
            if not prev_state.get(online_key, False):
                print(f"🎉 [誠品線上] 補貨上架！發送 LINE 通知: {online_title}")
                send_line_notification("誠品線上商城", online_title, url, is_instant_checkout=False)
            else:
                print(f"  ✨ [誠品線上] 依然有貨 - {online_title}")
        else:
            print(f"  💤 [{name} 線上] 缺貨中")

        store_key = f"{url}#store"
        curr_state[store_key] = store_stock
        if store_stock:
            if not prev_state.get(store_key, False):
                print(f"🎉 [誠品門市] 門市有貨！發送 LINE 通知: {store_title}")
                send_line_notification("誠品實體門市", store_title, url, is_instant_checkout=False)
            else:
                print(f"  ✨ [誠品門市] 依然有貨 - {store_title}")
        else:
            print(f"  💤 [{name} 門市] 缺貨中")
            
        time.sleep(1.5)
        
    save_state(curr_state)
    print(f"[{now}] ✅ 線上與實體門市掃描完成！")

if __name__ == "__main__":
    main()
