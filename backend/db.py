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
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT username, last_logout_at, last_login_at, COALESCE(is_logged_in, FALSE) FROM users")
    users = cur.fetchall()
    cur.close()
    conn.close()
    return users

def set_last_logout(username):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET last_logout_at = NOW(), is_logged_in = FALSE WHERE username=%s", (username,))
    conn.commit()
    cur.close()
    conn.close()

def set_last_login(username):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET last_login_at = NOW(), is_logged_in = TRUE WHERE username=%s", (username,))
    conn.commit()
    cur.close()
    conn.close()

def set_logged_in(username, value: bool):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET is_logged_in = %s WHERE username=%s", (value, username))
    conn.commit()
    cur.close()
    conn.close()

def username_exists(username: str) -> bool:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE username=%s LIMIT 1", (username,))
    exists = cur.fetchone() is not None
    cur.close()
    conn.close()
    return exists

def create_user(username: str, password: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (username, password, is_logged_in) VALUES (%s, %s, FALSE)",
        (username, password)
    )
    conn.commit()
    cur.close()
    conn.close()

# ---------- 이미지 관리 ----------
def get_all_images():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT name, image_ref, COALESCE(web_port, 80), COALESCE(vnc_port, 5900) FROM images ORDER BY name")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def get_image_by_ref(image_ref: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT name, image_ref, COALESCE(web_port, 80), COALESCE(vnc_port, 5900) FROM images WHERE image_ref=%s LIMIT 1", (image_ref,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row

def image_exists(name: str) -> bool:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM images WHERE name=%s LIMIT 1", (name,))
    exists = cur.fetchone() is not None
    cur.close()
    conn.close()
    return exists

def create_image(name: str, image_ref: str, web_port: int = 80, vnc_port: int = 5900):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO images (name, image_ref, web_port, vnc_port) VALUES (%s, %s, %s, %s)", (name, image_ref, web_port, vnc_port))
    conn.commit()
    cur.close()
    conn.close()

def delete_image(name: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM images WHERE name=%s", (name,))
    conn.commit()
    cur.close()
    conn.close()
