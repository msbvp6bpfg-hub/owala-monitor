import os
import sys
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

# 從 GitHub Secrets 環境變數讀取金鑰
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID = os.getenv("LINE_USER_ID", "")

def send_line_notification(store: str, title: str, url: str):
    """發送 LINE 補貨推播"""
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print("⚠️ 缺少 LINE 金鑰環境變數，略過推播")
        return

    msg_text = (
        f"🚨 【Owala FreeSip 補貨了！】\n\n"
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

def notify(store: str, title: str, url: str):
    print("\n" + "🔥" * 25)
    print(f"🎉 【Owala 補貨通知】\n通路：{store}\n商品：{title}\n連結：{url}")
    print("🔥" * 25 + "\n")
    send_line_notification(store, title, url)

def check_finders_html(url: str):
    try:
        res = requests.get(url, headers=HEADERS, impersonate="chrome120", timeout=10)
        res.encoding = "utf-8"
        soup = BeautifulSoup(res.text, "html.parser")
        h1 = soup.find("h1")
        title = h1.text.strip() if h1 else "Owala FreeSip 24oz"
        
        out_keywords = ["缺貨", "售完", "sold out", "暫無庫存", "補貨中"]
        has_out_keyword = any(kw in res.text.lower() for kw in out_keywords)
        
        if ("加入購物車" in res.text or "立即購買" in res.text) and not has_out_keyword:
            return True, title
        return False, title
    except Exception as e:
        print(f"  [Finders] 解析失敗: {e}")
    return False, "Owala FreeSip 24oz"

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
        title = h1.text.strip() if h1 else (soup.title.string.strip().split("-")[0].strip() if soup.title else "誠品 Owala FreeSip")
        
        out_keywords = ["已售完", "暫無庫存", "補貨中", "缺貨中"]
        has_out_keyword = any(kw in res.text for kw in out_keywords)
        
        if ("放入購物車" in res.text or "立即結帳" in res.text) and not has_out_keyword:
            return True, title
        return False, title
    except Exception as e:
        print(f"  [誠品] 解析失敗: {e}")
    return False, "誠品 Owala"

TARGET_LIST = [
    {"store": "Finders", "url": "https://www.finders.com.tw/products/owala-freesip-24oz", "checker": check_finders_html},
    {"store": "HOLA", "url": "https://www.hola.com.tw/p/014425080", "checker": check_hola_html},
    {"store": "誠品 (款式1)", "url": "https://www.eslite.com/product/10052271402683070020000", "checker": check_eslite_html},
    {"store": "誠品 (款式2)", "url": "https://www.eslite.com/product/10052271402683070019004", "checker": check_eslite_html},
    {"store": "誠品 (款式3)", "url": "https://www.eslite.com/product/10052271402683070017000", "checker": check_eslite_html},
    {"store": "誠品 (款式4)", "url": "https://www.eslite.com/product/10052271402683051103005", "checker": check_eslite_html},
]

def main():
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] 🚀 開始執行庫存掃描...")
    
    for item in TARGET_LIST:
        store = item["store"]
        url = item["url"]
        checker = item["checker"]
        
        in_stock, product_name = checker(url)
        
        if in_stock:
            notify(store, product_name, url)
        else:
            print(f"  💤 [{store}] 缺貨中 - {product_name}")
            
        time.sleep(1)
        
    print(f"[{now}] ✅ 掃描完成！")

if __name__ == "__main__":
    main()
