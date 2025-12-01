import logging
import secrets
import datetime
import os
import psutil
import time
import psycopg2
from dotenv import load_dotenv
from flask import Flask, session, jsonify, request, render_template
from flask_cors import CORS
from featuretoggles import TogglesList
from werkzeug.middleware.proxy_fix import ProxyFix
from prometheus_flask_exporter import PrometheusMetrics
from prometheus_client import Gauge, Histogram

load_dotenv()

SEAT_MAP = []
ROWS = "ABCDEFGHIJ" 
COLS = 10

for r_idx, row_char in enumerate(ROWS):
    for col_num in range(1, COLS + 1):
        s_type = "center"
        if r_idx < 3: s_type = "front" 
        elif r_idx > 7: s_type = "back" 
        if col_num <= 2 or col_num >= 19: s_type = "aisle"

        SEAT_MAP.append({
            "id": f"{row_char}{col_num}", 
            "row": row_char, 
            "col": col_num, 
            "type": s_type, 
            "status": 0
        })

class CinemaToggles(TogglesList):
    guest_checkout: bool
    auto_seating: bool

try:
    toggles = CinemaToggles("toggles.yaml")
except Exception:
    class Mock:
        guest_checkout = False
        auto_seating = False
    toggles = Mock()

os.environ["DEBUG_METRICS"] = "true"

app = Flask(__name__)   
app.secret_key = os.environ.get("SECRET_KEY", "dev-key-for-local-only")
DATABASE_URL = os.environ.get("DATABASE_URL") 

metrics = PrometheusMetrics(app, path='/metrics', group_by='path')
metrics.info('app_info', 'Cinema Booking App', version='1.0.3')

auto_seat_latency = Histogram('auto_seat_latency_seconds', 'Latency of smart seat allocation')
manual_seat_latency = Histogram('manual_seat_latency_seconds', 'Latency of manual seat selection')
auto_manual_seat_latency = Histogram('auto_manual_seat_latency_seconds', 'Latency of auto/manual seat selection')
system_cpu_usage = Gauge('system_cpu_usage_percent', 'System CPU usage percent')
system_memory_usage = Gauge('system_memory_usage_bytes', 'System memory usage in bytes')
db_write_latency = Gauge('db_write_latency_seconds', 'Latency of writing booking to DB')

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
# 判斷是否在 Render 環境 (Render 會自動注入 RENDER=true 這個變數)
IS_PRODUCTION = os.environ.get('RENDER') is not None

if IS_PRODUCTION:
    # 雲端環境 (HTTPS)：開啟安全限制
    app.config.update(
        SESSION_COOKIE_SAMESITE="None", 
        SESSION_COOKIE_SECURE=True
    )
else:
    # 本地環境 (HTTP)：放寬限制，不然 Cookie 會寫不進去
    app.config.update(
        SESSION_COOKIE_SAMESITE="Lax", 
        SESSION_COOKIE_SECURE=False
    )
CORS(app, supports_credentials=True)

# --- DB Helper ---
def get_db_connection():
    if not DATABASE_URL: return None
    try:
        return psycopg2.connect(DATABASE_URL)
    except Exception as e:
        logging.error(f"DB_CONNECTION_ERROR: {e}")
        return None

# --- [新增] 初始化座位庫存 (把 400 個位子塞進 DB) ---
def init_db_seats():
    conn = get_db_connection()
    if not conn: return
    try:
        cur = conn.cursor()
        # 檢查是否已經有票
        cur.execute("SELECT COUNT(*) FROM tickets")
        count = cur.fetchone()[0]
        
        if count == 0:
            logging.info("Initializing 400 seats into DB...")
            rows = "ABCDEFGHIJ"
            cols = 10
            args_list = []
            
            for r_idx, r in enumerate(rows):
                for c in range(1, cols + 1):
                    seat_code = f"{r}{c}"
                    s_type = "center"
                    if r_idx < 3: s_type = "front" 
                    elif r_idx > 6: s_type = "back" 
                    if c == 1 or c == 6 or c == 5 or c == 10: s_type = "aisle"
                    # 產生 TKT-001 格式
                    cur.execute("SELECT nextval('ticket_seq')")
                    seq = cur.fetchone()[0]
                    tkt_id = f"TKT-{seq:03d}"
                    args_list.append((tkt_id, seat_code, s_type))
            
            # 批次寫入
            sql = "INSERT INTO tickets (ticket_id, seat_code, seat_type) VALUES (%s, %s, %s)"
            cur.executemany(sql, args_list)
            conn.commit()
            logging.info("Seats initialized successfully.")
        
        cur.close()
        conn.close()
    except Exception as e:
        logging.error(f"Init DB failed: {e}")

# 應用程式啟動時，初始化 DB
with app.app_context():
    init_db_seats()

@app.before_request
def gather_system_metrics():
    try:
        cpu = psutil.cpu_percent(interval=None)
        system_cpu_usage.set(cpu)
        memory = psutil.Process(os.getpid()).memory_info().rss
        system_memory_usage.set(memory)
    except Exception as e:
        app.logger.error(f"Metrics error: {e}")

startup_logged = False
@app.before_request
def log_startup_once():
    global startup_logged
    if startup_logged: return
    startup_logged = True
    logging.info("STARTUP service=cinema_booking guest_checkout=%s auto_seating=%s",
        getattr(toggles, "guest_checkout", False), getattr(toggles, "auto_seating", False))

@app.route("/")
def page_index():
    logging.info("METRIC_PAGE_VIEW page=index role=%s", session.get("role", "anon"))
    return render_template("index.html")

@app.route("/login.html")
def page_login():
    logging.info("METRIC_PAGE_VIEW page=login role=%s", session.get("role", "anon"))
    return render_template("login.html")

@app.route("/booking_std.html")
def page_booking_std():
    logging.info("METRIC_PAGE_VIEW page=booking_std role=%s", session.get("role", "member"))
    return render_template("booking_std.html")

@app.route("/booking_guest.html")
def page_booking_guest():
    logging.info("METRIC_PAGE_VIEW page=booking_guest role=%s", session.get("role", "guest"))
    return render_template("booking_guest.html")

@app.route("/success.html")
def page_success():
    logging.info("METRIC_PAGE_VIEW page=success role=%s", session.get("role", "anon"))
    return render_template("success.html")

def generate_guest_token():
    return secrets.token_urlsafe(24)

@app.route("/api/init-flow", methods=["GET"])
def init_flow():
    if toggles.guest_checkout:
        token = generate_guest_token()
        session["guest_token"] = token
        session["role"] = "guest"
        logging.info("METRIC_FLOW_START type=guest_checkout token_prefix=%s", token[:8])
        return jsonify({"action": "redirect", "target": "booking_guest.html", "message": "進入快速訂票模式"})
    else:
        logging.info("FLOW_START type=member_only has_user_session=%s", "user_id" in session)
        if "user_id" in session:
            return jsonify({"action": "redirect", "target": "booking_std.html"})
        else:
            return jsonify({"action": "redirect", "target": "login.html"})

@app.route("/api/login", methods=["POST"])
def login():
    data = request.json
    username = data.get("username")
    if username == "admin" and data.get("password") == "1234":
        session["user_id"] = "admin"
        session["role"] = "member"
        logging.info("METRIC_LOGIN_SUCCESS user=%s", username)
        return jsonify({"success": True, "target": "booking_std.html"})
    logging.warning("SECURITY_LOGIN_FAILED user=%s", username)
    return jsonify({"success": False, "message": "帳號密碼錯誤"}), 401

@app.route("/api/seat-config", methods=["GET"])
def get_seat_config():
    mode = "auto" if toggles.auto_seating else "manual"
    
    response = {"mode": mode, "seats": [], "preferences": []}
    current_seat_map = list(SEAT_MAP)  # 複製目前座位狀態
    if mode == "manual":
        conn = get_db_connection()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("SELECT seat_code FROM tickets WHERE status = 1")
                sold_seats = {row[0] for row in cur.fetchall()}
                cur.close()
                conn.close()
                
                # 更新狀態
                for s in current_seat_map:
                    if s['id'] in sold_seats:
                        s['status'] = 1
            except: pass
        response["seats"] = current_seat_map
    else:
        response["preferences"] = [
            {"key": "center", "label": "👑 視野最佳 (中間區域)"},
            {"key": "aisle", "label": "🏃 進出方便 (靠走道)"},
            {"key": "back", "label": "🕶️ 隱密性高 (後排)"},
            {"key": "front", "label": "🔥 臨場感強 (前排)"},
        ]
    now = datetime.datetime.now(datetime.timezone.utc)
    session["seat_page_enter_at"] = now.isoformat()
    session["seat_mode"] = mode
    logging.info("METRIC_SEAT_PAGE_ENTER role=%s mode=%s time=%s", session.get("role", "anon"), mode, now.isoformat())
    return jsonify(response)

def allocate_seats(pref):
    condition_sql = "status = 0"
    if pref == "center":
        condition_sql += " AND seat_type = 'center'"
    elif pref == "aisle":
        condition_sql += " AND seat_type = 'aisle'"
    elif pref == "front":
        condition_sql += " AND seat_type = 'front'"
    elif pref == "back":
        condition_sql += " AND seat_type = 'back'"
    
    return condition_sql
@app.route("/api/book", methods=["POST"])
def book_ticket():
    data = request.json
    role = session.get("role")

    if role == "guest":
        if "guest_token" not in session:
            logging.warning("SECURITY_GUEST_NO_TOKEN")
            return jsonify({"error": "Security Violation: Invalid Guest Session"}), 403
        customer_id = f"GUEST-{data.get('email')}"
    elif role == "member":
        if "user_id" not in session:
            logging.warning("SECURITY_MEMBER_SESSION_EXPIRED")
            return jsonify({"error": "Session Expired"}), 401
        customer_id = f"MEMBER-{session.get('user_id')}"
    else:
        logging.warning("SECURITY_UNAUTHORIZED_BOOKING")
        return jsonify({"error": "Unauthorized"}), 401

    assigned_seats = []
    process_start = time.time()
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "DB Connection Failed"}), 500

    try:
        cur = conn.cursor()
        if toggles.auto_seating:
            
            time.sleep(2) # 注入兩秒延遲

            count = data.get('count', 1)
            pref = data.get('preference')

            condition_sql = allocate_seats(pref)

            cur.execute(f"""
                SELECT ticket_id, seat_code FROM tickets
                WHERE {condition_sql}
                ORDER BY ticket_id ASC
                LIMIT {count}
                FOR UPDATE SKIP LOCKED
            """)
            rows = cur.fetchall()

            if len(rows) < int(count):
                conn.rollback()
                return jsonify({"success": False, "error": f"所選區域 ({pref}) 剩餘座位不足"}), 400

            for row in rows:
                tkt_id, code = row
                cur.execute("""
                    UPDATE tickets SET status = 1
                    WHERE ticket_id = %s
                """, (tkt_id,))
                assigned_seats.append(code)

        #     assigned_seats = allocate_seats(pref, count)
        #     if not assigned_seats:
        #         logging.info("METRIC_BOOKING_FAILED reason=no_seat pref=%s count=%s", pref, count)
        #         return jsonify({"success": False, "error": "所選區域已無空位"}), 400
        #     logging.info("METRIC_AUTO_SEATING_USED role=%s pref=%s seats=%s", role, pref, assigned_seats)
        else:
            assigned_seats = data.get("selected_seats", [])
            if not assigned_seats:
                conn.rollback()
                return jsonify({"error": "未選擇座位"}), 400
            
            placeholders = ','.join(['%s'] * len(assigned_seats))
            cur.execute(f"""
                SELECT ticket_id, seat_code FROM tickets
                WHERE seat_code IN ({placeholders}) AND status = 0
                FOR UPDATE SKIP LOCKED
            """, tuple(assigned_seats))
            rows = cur.fetchall()

            if len(rows) < len(assigned_seats):
                conn.rollback()
                return jsonify({"success": False, "error": "所選座位已被搶先預訂"}), 400

            for row in rows:
                tkt_id, code = row
                cur.execute("UPDATE tickets SET status = 1 WHERE ticket_id = %s", (tkt_id,))

            # time.sleep(0.5) 
        
        cur.execute("SELECT nextval('order_seq')")
        seq = cur.fetchone()[0]
        order_id = f"ORD-{seq:03d}"

        process_duration = time.time() - process_start

        cur.execute(f"""
            INSERT INTO bookings (order_id, user_email, seat_codes, mode, processing_time_ms)
            VALUES (%s, %s, %s, %s, %s)
        """, (order_id, customer_id, ",".join(assigned_seats), "auto" if toggles.auto_seating else "manual", int(process_duration * 1000)))

        conn.commit()
        cur.close()
        conn.close()

        auto_manual_seat_latency.observe(process_duration)

        if toggles.auto_seating:
            auto_seat_latency.observe(process_duration)
            pref = data.get('preference', 'any')
            logging.info("METRIC_AUTO_SEATING_USED role=%s pref=%s seats=%s duration=%.3f", role, pref, assigned_seats, process_duration)
        else:
            manual_seat_latency.observe(process_duration)
            logging.info("METRIC_MANUAL_SEATING_USED role=%s seats=%s duration=%.3f", role, assigned_seats, process_duration)

        return jsonify({
            "success": True,
            "order_id": order_id,
            "seats": assigned_seats,
            "target": "success.html"
        })
    except Exception as e:
        if conn: conn.rollback()
        logging.error(f"Booking Failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, 
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    app.run(host="127.0.0.1", port=5000, debug=True)

if __name__ != "__main__":
    gunicorn_logger = logging.getLogger("gunicorn.error")
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)
    root_logger = logging.getLogger()
    root_logger.handlers = gunicorn_logger.handlers
    root_logger.setLevel(gunicorn_logger.level)