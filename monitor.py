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
    print(f"[{now}] ✅ 掃描完成！")

if __name__ == "__main__":
    main()
