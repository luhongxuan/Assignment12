import requests
import time
import random
import threading
from datetime import datetime

# 你的 Render 網址
BASE_URL = "https://assignment12-ia30.onrender.com/"

# 模擬 User-Agent
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) DevOps-Tester/4.0",
    "Content-Type": "application/json"
}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def simulate_real_guest_behavior():
    """
    v4 修正版：加入 Session 機制，確保 Server 能識別訪客身份
    """
    while True:
        # === 關鍵修正：建立 Session (就像打開瀏覽器) ===
        session = requests.Session()
        session.headers.update(HEADERS)
        
        try:
            # === Step 0: 取得訪客身份 (模擬點擊「立即開始」) ===
            # 這一步會讓 Server 在我們的 Cookie 裡寫入 session["role"] = "guest"
            init_res = session.get(f"{BASE_URL}/api/init-flow")
            if init_res.status_code != 200:
                log(f"⚠️ 無法初始化訪客身份: {init_res.status_code}")
                time.sleep(1)
                continue

            # === Step 1: 載入設定 (init) ===
            # 注意：這裡使用 session.get 而不是 requests.get，這樣才會帶上剛剛的 Cookie
            config_res = session.get(f"{BASE_URL}/api/seat-config")
            
            if config_res.status_code != 200:
                log(f"⚠️ 頁面載入失敗: {config_res.status_code}")
                time.sleep(1)
                continue

            config = config_res.json()
            current_mode = config.get('mode', 'unknown')
            
            payload = {
                "email": f"guest{random.randint(1000,9999)}@example.com",
                "count": 1, 
                "preference": None,
                "selected_seats": None,
                "movie": "devops-war" # 雖然 HTML 沒傳，但加著保險
            }
            
            log_msg = ""

            # === Step 2: 模擬選擇 ===
            if current_mode == 'auto':
                pref_options = config.get('preferences', [])
                if pref_options:
                    chosen_pref = random.choice(pref_options)
                    payload["preference"] = chosen_pref['key']
                    log_msg = f"🤖 [Auto] 選擇偏好: {chosen_pref['label']}"
                else:
                    # 如果 Auto 模式但沒回傳選項，可能是被降級了或 Server 怪怪的
                    # 我們嘗試直接送出一個預設值，模擬使用者盲按
                    payload["preference"] = "center"
                    log_msg = f"🤖 [Auto] 盲選偏好: center"

            elif current_mode == 'manual':
                all_seats = config.get('seats', [])
                available_seats = [s['id'] for s in all_seats if s['status'] == 0]
                
                if not available_seats:
                    log("🈵 [Manual] 客滿了")
                    time.sleep(1)
                    continue
                
                chosen_seat = random.choice(available_seats)
                payload["selected_seats"] = [chosen_seat]
                log_msg = f"👆 [Manual] 點選座位: {chosen_seat}"

            else:
                log(f"❓ 未知模式: {current_mode}")
                time.sleep(1)
                continue

            # 模擬思考
            time.sleep(random.uniform(0.1, 0.3))

            # === Step 3: 送出訂單 ===
            # 這裡一樣要用 session.post 帶上 Cookie
            book_res = session.post(f"{BASE_URL}/api/book", json=payload)
            
            if book_res.status_code == 200:
                res_data = book_res.json()
                log(f"✅ {log_msg} -> 成功! Order: {res_data.get('order_id')}")
            else:
                log(f"❌ {log_msg} -> 失敗: {book_res.status_code} - {book_res.text}")

        except Exception as e:
            log(f"🔥 連線錯誤: {e}")
        
        # 每次訂完票就換一個「新使用者」(重置 Session)，或者是繼續訂
        # 這裡我們選擇繼續循環，但因為 session 變數是在 while 內宣告的
        # 所以每次 loop 都是一個新使用者 (符合訪客情境)
        time.sleep(0.5)

if __name__ == "__main__":
    print(f"🚀 [v4 最終修正版] 啟動針對 {BASE_URL} 的訪客模擬...")
    print("已修正 401 Unauthorized 問題 (加入 Session Cookie 支援)")
    print("按 Ctrl+C 停止")

    threads = []
    for i in range(2):
        t = threading.Thread(target=simulate_real_guest_behavior)
        t.start()
        threads.append(t)

    for t in threads:
        t.join()