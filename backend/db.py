import psycopg2
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT,
        dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD
    )

def get_user_by_username(username):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username=%s", (username,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return user

def get_admin_by_username(username):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM admins WHERE username=%s", (username,))
    admin = cur.fetchone()
    cur.close()
    conn.close()
    return admin

def get_all_users():
    # username, last_logout_at, last_login_at, is_logged_in 모두 조회
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT username, last_logout_at, last_login_at, COALESCE(is_logged_in, FALSE) FROM users")
    users = cur.fetchall()
    cur.close()
    conn.close()
    return users

def set_last_logout(username):
    # 로그아웃/종료 시각 기록 + 로그인 상태 false
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET last_logout_at = NOW(), is_logged_in = FALSE WHERE username=%s", (username,))
    conn.commit()
    cur.close()
    conn.close()

def set_last_login(username):
    # 로그인 시각 기록 + 로그인 상태 true
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET last_login_at = NOW(), is_logged_in = TRUE WHERE username=%s", (username,))
    conn.commit()
    cur.close()
    conn.close()

def set_logged_in(username, value: bool):
    # 로그인 상태만 토글하고 싶을 때 사용
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET is_logged_in = %s WHERE username=%s", (value, username))
    conn.commit()
    cur.close()
    conn.close()

# ---------- 신규 계정 생성/중복 확인 ----------
def username_exists(username: str) -> bool:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE username=%s LIMIT 1", (username,))
    exists = cur.fetchone() is not None
    cur.close()
    conn.close()
    return exists

def create_user(username: str, password: str):
    # 간단 구현: 비밀번호 평문 저장 (추후 bcrypt로 변경 권장)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (username, password, is_logged_in) VALUES (%s, %s, FALSE)",
        (username, password)
    )
    conn.commit()
    cur.close()
    conn.close()
