from flask import Flask, render_template, request, redirect, session, url_for
from db import (
    get_db_connection,
    get_user_by_username,
    get_admin_by_username,
    get_all_users,
    set_last_logout,   # 로그아웃/종료 시각 기록 + is_logged_in=false
    set_last_login,    # 로그인 시각 기록 + is_logged_in=true
)
from kubernetes import client, config
from datetime import datetime

app = Flask(__name__)
app.secret_key = "super-secret-key-1234"

# ----------------############## POD/GUI + 유저별 NodePort 서비스 #####################----------------

def ensure_gui_pod(user: str):
    """
    - gui-<user> POD가 없으면 생성
    - gui-svc-<user> Service(NodePort): 30680 + <유저명 숫자> 규칙 (범위 밖/숫자없음 → 자동할당)
    - gui_url 반환: http://<node_ip>:<node_port>/
    """
    config.load_kube_config()
    namespace = "default"
    pod_name = f"gui-{user}"
    svc_name = f"gui-svc-{user}"
    node_ip = "192.168.2.111"  # 환경에 맞게 노드 IP 설정

    v1 = client.CoreV1Api()

    # 1) POD 확인/생성
    pods = v1.list_namespaced_pod(namespace=namespace, label_selector=f"user={user}")
    if len(pods.items) == 0:
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

    # 2) Service 확인/생성
    try:
        svc = v1.read_namespaced_service(name=svc_name, namespace=namespace)
    except Exception:
        node_port_value = None
        try:
            suffix_number_str = "".join([c for c in user if c.isdigit()])
            if suffix_number_str:
                suffix_number = int(suffix_number_str)
                node_port_value = 30680 + suffix_number
                # NodePort 기본 허용 범위(30000~32767) 검증
                if node_port_value < 30000 or node_port_value > 32767:
                    node_port_value = None
            else:
                node_port_value = None
        except:
            node_port_value = None

        service_manifest = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": svc_name},
            "spec": {
                "type": "NodePort",
                "selector": {"user": user},
                "ports": [{
                    "port": 80,
                    "targetPort": 80,
                    "protocol": "TCP",
                    **({"nodePort": node_port_value} if node_port_value else {})
                }]
            }
        }
        v1.create_namespaced_service(namespace=namespace, body=service_manifest)
        svc = v1.read_namespaced_service(name=svc_name, namespace=namespace)

    # 3) gui_url
    node_port = svc.spec.ports[0].node_port
    gui_url = f"http://{node_ip}:{node_port}/"
    return pod_name, "EXISTS", gui_url

def delete_gui_pod(user: str):
    """
    종료(terminate) 동작: POD 삭제 + 최근접속시간 업데이트(set_last_logout)
    """
    config.load_kube_config()
    namespace = "default"
    pod_name = f"gui-{user}"
    v1 = client.CoreV1Api()
    try:
        v1.delete_namespaced_pod(name=pod_name, namespace=namespace)
    except Exception:
        pass
    # 종료 시각 기록 + is_logged_in = FALSE
    set_last_logout(user)

def check_gui_pod(user: str) -> bool:
    """
    해당 유저의 POD가 Running인지 확인 (상태 ONLINE/OFFLINE 판단용)
    """
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
            # 로그인 시각 기록 + 로그인 상태 true
            set_last_login(username)
            # POD/Service 준비
            ensure_gui_pod(username)
            # 준비 화면 후 /desktop으로 이동
            return render_template("waiting.html", gui_url=url_for('desktop'))
        else:
            return render_template("login.html", message="로그인 실패")
    return render_template("login.html")

@app.route("/desktop")
def desktop():
    username = session.get('username')
    if not username:
        return redirect(url_for('login'))
    pod, status, gui_url = ensure_gui_pod(username)
    return render_template("desktop.html", gui_url=gui_url, username=username)

# 로그아웃(세션만 종료, POD 유지 → ONLINE, 최근접속시간은 로그아웃 시각)
@app.route("/logout", methods=["POST"])
def logout():
    username = request.form.get("username", None) or session.get("username")
    if username:
        # 로그아웃 시각 기록 + 로그인 상태 false
        set_last_logout(username)
        session.pop('username', None)
    return render_template("logged_out.html")

# 종료(세션종료 + POD 삭제 → OFFLINE, 최근접속시간은 종료 시각)
@app.route("/terminate", methods=["POST"])
def terminate():
    username = request.form.get("username", None) or session.get("username")
    if username:
        delete_gui_pod(username)   # 내부에서 set_last_logout 호출
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

# ----------------### 관리자 대시보드 ###------------------------

def _username_sort_key(username: str):
    """
    user1, user2... 순으로 정렬하기 위한 키 생성
    숫자가 있으면 숫자 기준, 없으면 문자열 기준으로 뒤쪽 배치
    """
    digits = "".join([c for c in username if c.isdigit()])
    if digits:
        return (int(digits), username)
    return (10**9, username)

@app.route("/admin_dashboard")
def admin_dashboard():
    if not session.get("admin_logged_in"):
        return redirect(url_for('admin_login'))

    # 모니터링 데이터 예시 (실 운영에서는 실제 값으로 교체)
    total_cpu_percent = 4.1
    used_cores = 1.0
    total_cores = 24
    total_mem_percent = 25.9
    mem_used_gb = 11.9
    mem_total_gb = 46.1
    cpu_top5 = [("k8s-worker02", 1.2), ("k8s-worker01", 1.1), ("k8s-master01", 0.9)]
    mem_top5 = [("k8s-worker01", 25.1), ("k8s-worker02", 22.9), ("k8s-master01", 19.6)]

    # 유저 관리: username, last_logout_at, last_login_at, is_logged_in 조회
    raw_users = get_all_users()
    users_sorted = sorted(raw_users, key=lambda row: _username_sort_key(row[0]))

    user_status_list = []
    for username, last_logout_at, last_login_at, is_logged_in in users_sorted:
        pod_online = check_gui_pod(username)
        status = "ONLINE" if pod_online else "OFFLINE"

        # 표시 규칙:
        # - POD Running이고 is_logged_in=True: "로그인중"
        # - POD Running이고 is_logged_in=False: last_logout_at
        # - POD OFFLINE: last_logout_at
        if pod_online and is_logged_in:
            recent_time = "로그인중"
        else:
            if last_logout_at:
                recent_time = last_logout_at.strftime("%Y-%m-%d %H:%M:%S")
            elif last_login_at:
                recent_time = last_login_at.strftime("%Y-%m-%d %H:%M:%S")
            else:
                recent_time = "-"

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
