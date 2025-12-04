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
    cur.execute("SELECT username, last_logout_at FROM users")
    users = cur.fetchall()
    cur.close()
    conn.close()
    return users

def set_last_logout(username):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET last_logout_at = NOW() WHERE username=%s", (username,))
    conn.commit()
    cur.close()
    conn.close()
