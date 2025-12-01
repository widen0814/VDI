from flask import Blueprint, render_template, request
from db import db
from sqlalchemy import text

user_bp = Blueprint("user", __name__)

@user_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')
    username = request.form['username']
    password = request.form['password']
    # DB 조회 및 인증
    result = db.session.execute(
        text("SELECT * FROM users WHERE username=:username AND password=:password"),
        {"username": username, "password": password}
    )
    user = result.fetchone()
    if user:
        return f"로그인 성공! 환영합니다, {username}"
    else:
        return render_template('login.html', error="로그인 실패! 아이디 또는 비밀번호가 틀렸습니다.")
