import pytest
from app import app
from flask import session

# --- 測試環境設定 (Fixture) ---
@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.secret_key = 'test-secret-key'
    # 使用 Flask 的測試客戶端，這樣不用真的啟動伺服器也能測
    with app.test_client() as client:
        yield client

# --- 測試案例 1: 驗證 Toggle OFF (回歸測試) ---
def test_toggle_off_redirects_to_login(client, mocker):
    """
    場景：當 guest_checkout 關閉時，訪客應該被導向登入頁
    """
    # [Mock] 強制把 Toggle 關掉 (不管 yaml 設定是什麼)
    mocker.patch('app.toggles.guest_checkout', False)

    # 模擬發送請求
    response = client.get('/api/init-flow')
    data = response.get_json()

    # [Assert] 驗證結果
    assert response.status_code == 200
    assert data['action'] == 'redirect'
    assert 'login.html' in data['target']

# --- 測試案例 2: 驗證 Toggle ON (假設一：免登入) ---
def test_toggle_on_allows_guest_checkout(client, mocker):
    """
    場景：當 guest_checkout 開啟時，訪客應獲得 Token 並進入免登入頁
    """
    # [Mock] 強制把 Toggle 打開
    mocker.patch('app.toggles.guest_checkout', True)

    response = client.get('/api/init-flow')
    data = response.get_json()

    # [Assert] 驗證 API 回應
    assert data['action'] == 'redirect'
    assert 'booking_guest.html' in data['target']
    
    # [Assert] 驗證 Session (這就是 A&A 的自動化驗證)
    with client.session_transaction() as sess:
        assert 'guest_token' in sess
        assert sess['role'] == 'guest'

# --- 測試案例 3: 驗證 Toggle ON (假設二：智慧配位) ---
def test_auto_seating_allocation(client, mocker):
    """
    場景：當 auto_seating 開啟時，系統應回傳偏好選項而非地圖
    """
    mocker.patch('app.toggles.auto_seating', True)

    response = client.get('/api/seat-config')
    data = response.get_json()

    # 驗證模式是否切換為 auto
    assert data['mode'] == 'auto'
    assert len(data['preferences']) > 0  # 應該要有選項
    assert len(data['seats']) == 0       # 不該回傳地圖

# --- 測試案例 4: 安全性測試 (Security / Negative Test) ---
def test_security_violation_no_session(client):
    """
    場景：駭客在沒有 Session (沒按開始) 的情況下，直接呼叫訂票 API
    """
    # 這裡我們不呼叫 init-flow，直接 POST book
    payload = {
        "email": "hacker@example.com",
        "movie": "devops-war",
        "seats": ["A1"]
    }
    
    response = client.post('/api/book', json=payload)
    
    # [Assert] 預期系統要擋下來 (401 Unauthorized)
    assert response.status_code == 401
    assert "Unauthorized" in response.get_json()['error']