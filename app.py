import logging
import secrets
import datetime
import os
import psutil
from flask import Flask, session, jsonify, request, render_template
from flask_cors import CORS
from featuretoggles import TogglesList
from werkzeug.middleware.proxy_fix import ProxyFix
from prometheus_flask_exporter import PrometheusMetrics
from prometheus_client import Gauge

SEAT_MAP = [
    {"id": "A1", "row": "A", "col": 1, "type": "front", "status": 0},
    {"id": "A2", "row": "A", "col": 2, "type": "front", "status": 0},
    {"id": "A3", "row": "A", "col": 3, "type": "center", "status": 0},
    {"id": "A4", "row": "A", "col": 4, "type": "front", "status": 0},
    {"id": "A5", "row": "A", "col": 5, "type": "aisle", "status": 1},
    {"id": "B1", "row": "B", "col": 1, "type": "back", "status": 0},
    {"id": "B2", "row": "B", "col": 2, "type": "back", "status": 0},
    {"id": "B3", "row": "B", "col": 3, "type": "center", "status": 0},
]


class CinemaToggles(TogglesList):
    guest_checkout: bool
    auto_seating: bool


try:
    toggles = CinemaToggles("toggles.yaml")
except Exception:
    # toggles.yaml 沒載到時，保守預設都關閉
    class Mock:
        guest_checkout = False
        auto_seating = False

    toggles = Mock()

os.environ["DEBUG_METRICS"] = "true"

app = Flask(__name__)   
app.secret_key = os.environ.get("SECRET_KEY", "dev-key-for-local-only")

metrics = PrometheusMetrics(app)
metrics.info('app_info', 'Cinema Booking App', version='1.0.3')

system_cpu_usage = Gauge('system_cpu_usage_percent', 'System CPU usage percent')
system_memory_usage = Gauge('system_memory_usage_bytes', 'System memory usage in bytes')

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

app.config.update(SESSION_COOKIE_SAMESITE="None", SESSION_COOKIE_SECURE=True)

CORS(app, supports_credentials=True)

if __name__ != "__main__":
    gunicorn_logger = logging.getLogger("gunicorn.error")
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)
    root_logger = logging.getLogger()
    root_logger.handlers = gunicorn_logger.handlers
    root_logger.setLevel(gunicorn_logger.level)


@app.before_request
def gather_system_metrics():
    # 每次有請求進來時，順便抓一下 CPU 和 Memory
    try:
        # 抓取 CPU 使用率 (non-blocking)
        cpu = psutil.cpu_percent(interval=None)
        system_cpu_usage.set(cpu)
        
        # 抓取記憶體使用量 (RSS)
        memory = psutil.Process(os.getpid()).memory_info().rss
        system_memory_usage.set(memory)
    except Exception as e:
        app.logger.error(f"Metrics error: {e}")

startup_logged = False

@app.before_request
def log_startup_once():
    global startup_logged
    if startup_logged:
        return

    startup_logged = True
    logging.info(
        "STARTUP service=cinema_booking "
        "guest_checkout=%s auto_seating=%s",
        getattr(toggles, "guest_checkout", False),
        getattr(toggles, "auto_seating", False),
    )


@app.route("/")
def page_index():
    # 頁面 view 也可以當 metric：首頁被看了幾次
    logging.info("METRIC_PAGE_VIEW page=index role=%s", session.get("role", "anon"))
    return render_template("index.html")


@app.route("/login.html")
def page_login():
    logging.info("METRIC_PAGE_VIEW page=login role=%s", session.get("role", "anon"))
    return render_template("login.html")


@app.route("/booking_std.html")
def page_booking_std():
    logging.info(
        "METRIC_PAGE_VIEW page=booking_std role=%s", session.get("role", "member")
    )
    return render_template("booking_std.html")


@app.route("/booking_guest.html")
def page_booking_guest():
    logging.info(
        "METRIC_PAGE_VIEW page=booking_guest role=%s", session.get("role", "guest")
    )
    return render_template("booking_guest.html")


@app.route("/success.html")
def page_success():
    logging.info(
        "METRIC_PAGE_VIEW page=success role=%s", session.get("role", "anon")
    )
    return render_template("success.html")


bookings_db = []

def generate_guest_token():
    return secrets.token_urlsafe(24)

@app.route("/api/init-flow", methods=["GET"])
def init_flow():
    if toggles.guest_checkout:
        token = generate_guest_token()
        session["guest_token"] = token
        session["role"] = "guest"

        # Flow 開始，可用來計算「免登入訂票」啟動次數
        logging.info(
            "METRIC_FLOW_START type=guest_checkout token_prefix=%s", token[:8]
        )

        return jsonify(
            {
                "action": "redirect",
                "target": "booking_guest.html",
                "message": "進入快速訂票模式",
            }
        )
    else:
        logging.info(
            "FLOW_START type=member_only has_user_session=%s",
            "user_id" in session,
        )
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

    if mode == "manual":
        response["seats"] = SEAT_MAP
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

    logging.info(
        "METRIC_SEAT_PAGE_ENTER role=%s mode=%s time=%s",
        session.get("role", "anon"),
        mode,
        now.isoformat(),
    )

    return jsonify(response)


def allocate_seats(pref, count):
    count = int(count)
    available = [s for s in SEAT_MAP if s['status'] == 0]
    
    if pref == 'center':
        candidates = [s for s in available if s['col'] == 3]
    elif pref == 'aisle':
        candidates = [s for s in available if s['col'] in [1, 5]]
    elif pref == 'back':
        candidates = [s for s in available if s['row'] == 'B']
    else:
        candidates = available
        
    if len(candidates) < count:
        candidates = available

    if len(candidates) < count:
        return None
        
    selected = candidates[:count]
    ids = []
    for s in selected:
        s['status'] = 1
        ids.append(s['id'])
        
    return ids


@app.route("/api/book", methods=["POST"])
def book_ticket():
    data = request.json
    role = session.get("role")

    if role == "guest":
        if "guest_token" not in session:
            logging.warning("SECURITY_GUEST_NO_TOKEN")
            return jsonify({"error": "Security Violation: Invalid Guest Session"}), 403
        customer_id = f"GUEST-{data.get('email')}"
        logging.info("ORDER_PROCESS role=guest customer=%s", customer_id)
    elif role == "member":
        if "user_id" not in session:
            logging.warning("SECURITY_MEMBER_SESSION_EXPIRED")
            return jsonify({"error": "Session Expired"}), 401
        customer_id = f"MEMBER-{session.get('user_id')}"
        logging.info("ORDER_PROCESS role=member customer=%s", customer_id)
    else:
        logging.warning("SECURITY_UNAUTHORIZED_BOOKING")
        return jsonify({"error": "Unauthorized"}), 401

    assigned_seats = []

    if toggles.auto_seating:
        pref = data.get('preference')
        count = data.get('count', 1)
        assigned_seats = allocate_seats(pref, count)
        if not assigned_seats:
            logging.info(
                "METRIC_BOOKING_FAILED reason=no_seat pref=%s count=%s", pref, count
            )
            return (
                jsonify({"success": False, "error": "所選區域已無空位"}),
                400,
            )
        logging.info(
            "METRIC_AUTO_SEATING_USED role=%s pref=%s seats=%s",
            role,
            pref,
            assigned_seats,
        )
    else:
        assigned_seats = data.get("selected_seats")
        logging.info(
            "METRIC_MANUAL_SEATING_USED role=%s seats=%s", role, assigned_seats
        )

    seat_enter_str = session.pop("seat_page_enter_at", None)
    seat_mode = session.pop("seat_mode", "unknown")
    seat_duration = None
    if seat_enter_str:
        try:
            start = datetime.datetime.fromisoformat(seat_enter_str)
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            seat_duration = (now_utc - start).total_seconds()
        except Exception:
            seat_duration = None

    if seat_duration is not None:
        logging.info(
            "METRIC_SEAT_PAGE_DURATION role=%s mode=%s duration_s=%.3f",
            role,
            seat_mode,
            seat_duration,
        )

    order_id = f"ORD-{secrets.token_hex(4).upper()}"
    order = {
        "id": order_id,
        "customer": customer_id,
        "movie": data.get("movie"),
        "seats": assigned_seats,
        "time": datetime.datetime.now().isoformat(),
    }
    bookings_db.append(order)

    logging.info(
        "METRIC_BOOKING_COMPLETED role=%s customer=%s order=%s seats=%s",
        role,
        customer_id,
        order_id,
        assigned_seats,
    )

    return jsonify(
        {
            "success": True,
            "order_id": order_id,
            "seats": assigned_seats,
            "target": "success.html",
        }
    )

print("=== 目前所有註冊的路由 ===")
print(app.url_map)
print("========================")

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)