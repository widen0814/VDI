from flask import Flask, render_template, request, redirect, session, url_for
from db import (
    get_db_connection,
    get_user_by_username,
    get_admin_by_username,
    get_all_users,
    set_last_logout
)
from kubernetes import client, config
from datetime import datetime

app = Flask(__name__)
app.secret_key = "super-secret-key-1234"

# ----------------############## POD/GUI 기능 #####################----------------

def ensure_gui_pod(user):
    config.load_kube_config()
    namespace = "default"
    pod_name = f"gui-{user}"
    v1 = client.CoreV1Api()
    pods = v1.list_namespaced_pod(namespace=namespace, label_selector=f"user={user}")
    if len(pods.items) > 0:
        return pod_name, "EXISTS", "http://192.168.2.111:30680/"
    pod_manifest = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": pod_name,
            "labels": {"user": user},
            "annotations": {"sidecar.istio.io/inject": "false"}
        },
        "spec": {
            "containers": [{
                "name": "gui",
                "image": "dorowu/ubuntu-desktop-lxde-vnc",
                "ports": [
                    {"containerPort": 80},
                    {"containerPort": 5900}
                ]
            }]
        }
    }
    v1.create_namespaced_pod(namespace=namespace, body=pod_manifest)
    return pod_name, "CREATED", "http://192.168.2.111:30680/"

def delete_gui_pod(user):
    config.load_kube_config()
    namespace = "default"
    pod_name = f"gui-{user}"
    v1 = client.CoreV1Api()
    try:
        v1.delete_namespaced_pod(name=pod_name, namespace=namespace)
    except Exception:
        pass
    set_last_logout(user)

def check_gui_pod(user):
    config.load_kube_config()
    namespace = "default"
    pod_name = f"gui-{user}"
    v1 = client.CoreV1Api()
    try:
        pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        return pod.status.phase == "Running"
    except Exception:
        return False

# ----------------############## 유저/관리자 로그인/로그아웃 #####################----------------

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = get_user_by_username(username)
        if user and user[2] == password:
            session['username'] = username
            pod, status, gui_url = ensure_gui_pod(username)
            return render_template("waiting.html", gui_url=url_for('desktop'))
        else:
            return render_template("login.html", message="로그인 실패")
    return render_template("login.html")

@app.route("/desktop")
def desktop():
    username = session.get('username')
    if not username:
        return redirect(url_for('login'))
    gui_url = "http://192.168.2.111:30680/"
    return render_template("desktop.html", gui_url=gui_url, username=username)

# 로그아웃(세션만 종료, POD 유지, 상태: ONLINE)
@app.route("/logout", methods=["POST"])
def logout():
    username = request.form.get("username", None) or session.get("username")
    if username:
        set_last_logout(username)  # 최근접속시간 기록
        session.pop('username', None)
    return render_template("logged_out.html")

# 종료(세션종료 + POD 삭제, 상태: OFFLINE)
@app.route("/terminate", methods=["POST"])
def terminate():
    username = request.form.get("username", None) or session.get("username")
    if username:
        delete_gui_pod(username)
        session.pop('username', None)
    return render_template("logged_out.html")

@app.route("/admin_login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        admin = get_admin_by_username(username)
        if admin and admin[2] == password:
            session['admin_logged_in'] = True
            session['admin_name'] = username
            return redirect(url_for('admin_dashboard'))
        else:
            return render_template("admin_login.html", message="로그인 실패")
    return render_template("admin_login.html")

@app.route("/admin_logout", methods=["POST"])
def admin_logout():
    session.pop("admin_logged_in", None)
    session.pop("admin_name", None)
    return redirect(url_for('admin_login'))

@app.route("/admin_dashboard")
def admin_dashboard():
    if not session.get("admin_logged_in"):
        return redirect(url_for('admin_login'))
    # 모니터링 데이터 예시 (실제 값은 시스템에서 읽을 것)
    total_cpu_percent = 4.1
    used_cores = 1.0
    total_cores = 24
    total_mem_percent = 25.9
    mem_used_gb = 11.9
    mem_total_gb = 46.1
    cpu_top5 = [("k8s-worker02", 1.2), ("k8s-worker01", 1.1), ("k8s-master01", 0.9)]
    mem_top5 = [("k8s-worker01", 25.1), ("k8s-worker02", 22.9), ("k8s-master01", 19.6)]

    # 유저 관리: users + pod 상태 조합
    users = get_all_users()
    user_status_list = []
    for username, last_logout_at in users:
        pod_online = check_gui_pod(username)
        status = "ONLINE" if pod_online else "OFFLINE"
        recent_time = last_logout_at.strftime("%Y-%m-%d %H:%M:%S") if last_logout_at else "-"
        user_status_list.append({
            "username": username,
            "status": status,
            "recent_time": recent_time
        })
    return render_template(
        "admin_dashboard.html",
        admin_name=session.get("admin_name"),
        total_cpu_percent=total_cpu_percent,
        used_cores=used_cores,
        total_cores=total_cores,
        total_mem_percent=total_mem_percent,
        mem_used_gb=mem_used_gb,
        mem_total_gb=mem_total_gb,
        cpu_top5=cpu_top5,
        mem_top5=mem_top5,
        user_status_list=user_status_list
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
