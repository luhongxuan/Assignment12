TRUNCATE TABLE bookings RESTART IDENTITY;
SELECT * FROM bookings;

DROP TABLE IF EXISTS bookings;

-- 1. 建立 Tickets 表 (庫存)
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id VARCHAR(20) PRIMARY KEY, -- TKT-001
    seat_code VARCHAR(10) NOT NULL,    -- A1
    status INTEGER DEFAULT 0           -- 0=空, 1=已售
);

-- 2. 建立 Bookings 表 (訂單，PM 指定的主鍵格式)
CREATE TABLE IF NOT EXISTS bookings (
    order_id VARCHAR(20) PRIMARY KEY,  -- ORD-001
    user_email VARCHAR(255),
    seat_codes TEXT,
    mode VARCHAR(10),                  -- 'auto' or 'manual'
    processing_time_ms FLOAT,          -- 處理耗時
    created_at TIMESTAMP DEFAULT NOW()
);

-- 3. 建立一個 Sequence 用來產生 TKT-XXX 和 ORD-XXX 的流水號
CREATE SEQUENCE IF NOT EXISTS ticket_seq START 1;
CREATE SEQUENCE IF NOT EXISTS order_seq START 1;

-- 4. 清空舊資料 (重置用)
TRUNCATE TABLE tickets, bookings RESTART IDENTITY;
ALTER SEQUENCE ticket_seq RESTART WITH 1;
ALTER SEQUENCE order_seq RESTART WITH 1;

SELECT * FROM tickets WHERE status = '1' LIMIT 5;
SELECT * FROM bookings LIMIT 5;

ALTER TABLE tickets ADD COLUMN seat_type VARCHAR(10);