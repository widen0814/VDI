from flask import Flask, render_template, request, redirect, session, url_for, flash, jsonify
from db import (
    get_db_connection,
    get_user_by_username,
    get_admin_by_username,
    get_all_users,
    set_last_logout,
    set_last_login,
    username_exists,
    create_user,
)
from kubernetes import client, config
from datetime import datetime, timezone, timedelta
import requests
from config import PROMETHEUS_URL

app = Flask(__name__)
app.secret_key = "super-secret-key-1234"

KST = timezone(timedelta(hours=9))

def to_kst(dt: datetime) -> str:
    if not dt: return "-"
    try:
        if dt.tzinfo is None:
            dt_utc = dt.replace(tzinfo=timezone.utc)
            dt_kst = dt_utc.astimezone(KST)
        else:
            dt_kst = dt.astimezone(KST)
        return dt_kst.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return dt.strftime("%Y-%m-%d %H:%M:%S")

def ensure_gui_pod(user: str):
    config.load_kube_config()
    namespace = "default"
    pod_name = f"gui-{user}"
    svc_name = f"gui-svc-{user}"
    node_ip = "192.168.2.111"

    v1 = client.CoreV1Api()
    pods = v1.list_namespaced_pod(namespace=namespace, label_selector=f"user={user}")
    if len(pods.items) == 0:
        pod_manifest = {
            "apiVersion":"v1","kind":"Pod",
            "metadata":{"name":pod_name,"labels":{"user":user},"annotations":{"sidecar.istio.io/inject":"false"}},
            "spec":{"containers":[{"name":"gui","image":"dorowu/ubuntu-desktop-lxde-vnc","ports":[{"containerPort":80},{"containerPort":5900}]}]}
        }
        v1.create_namespaced_pod(namespace=namespace, body=pod_manifest)

    try:
        svc = v1.read_namespaced_service(name=svc_name, namespace=namespace)
    except Exception:
        node_port_value = None
        try:
            suffix_number_str = "".join([c for c in user if c.isdigit()])
            if suffix_number_str:
                suffix_number = int(suffix_number_str)
                node_port_value = 30680 + suffix_number
                if node_port_value < 30000 or node_port_value > 32767:
                    node_port_value = None
        except:
            node_port_value = None

        service_manifest = {
            "apiVersion":"v1","kind":"Service","metadata":{"name":svc_name},
            "spec":{"type":"NodePort","selector":{"user":user},
                    "ports":[{"port":80,"targetPort":80,"protocol":"TCP",**({"nodePort":node_port_value} if node_port_value else {})}]}
        }
        v1.create_namespaced_service(namespace=namespace, body=service_manifest)
        svc = v1.read_namespaced_service(name=svc_name, namespace=namespace)

    node_port = svc.spec.ports[0].node_port
    gui_url = f"http://{node_ip}:{node_port}/"
    return pod_name, "EXISTS", gui_url

def delete_gui_pod(user: str):
    config.load_kube_config()
    namespace = "default"
    pod_name = f"gui-{user}"
    v1 = client.CoreV1Api()
    try:
        v1.delete_namespaced_pod(name=pod_name, namespace=namespace)
    except Exception:
        pass
    set_last_logout(user)

def check_gui_pod(user: str) -> bool:
    config.load_kube_config()
    namespace = "default"
    pod_name = f"gui-{user}"
    v1 = client.CoreV1Api()
    try:
        pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        return pod.status.phase == "Running"
    except Exception:
        return False

def prom_query(query: str):
    url = f"{PROMETHEUS_URL}/api/v1/query"
    resp = requests.get(url, params={"query": query}, timeout=5)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "success":
        raise RuntimeError(f"Prometheus query failed: {data}")
    return data["data"]["result"]

def get_cluster_cpu_usage():
    idle_rate = prom_query('avg(rate(node_cpu_seconds_total{mode="idle"}[1m])) by (instance)')
    cores_per_node = prom_query('count(node_cpu_seconds_total{mode="idle"}) by (instance)')

    idle_map = {item["metric"].get("instance",""): float(item["value"][1]) for item in idle_rate}
    core_map = {item["metric"].get("instance",""): float(item["value"][1]) for item in cores_per_node}

    node_usage_list = []
    total_used_cores = 0.0
    total_cores = 0.0

    for inst, cores in core_map.items():
        idle = idle_map.get(inst)
        if idle is None: continue
        usage_ratio = max(0.0, min(1.0, 1.0 - idle))
        used_cores = usage_ratio * cores
        node_usage_list.append({"node": inst, "usage_percent": usage_ratio * 100.0})
        total_used_cores += used_cores
        total_cores += cores

    node_usage_list.sort(key=lambda x: x["usage_percent"], reverse=True)
    cpu_top5 = [(n["node"], round(n["usage_percent"], 2)) for n in node_usage_list[:5]]
    total_cpu_percent = round((total_used_cores / total_cores) * 100.0, 1) if total_cores > 0 else 0.0
    return {"total_cpu_percent": total_cpu_percent, "used_cores": round(total_used_cores,1), "total_cores": int(total_cores), "cpu_top5": cpu_top5}

def get_cluster_memory_usage():
    mem_total = prom_query('node_memory_MemTotal_bytes')
    mem_avail = prom_query('node_memory_MemAvailable_bytes')

    total_bytes_map = {item["metric"].get("instance",""): float(item["value"][1]) for item in mem_total}
    avail_bytes_map = {item["metric"].get("instance",""): float(item["value"][1]) for item in mem_avail}

    node_mem_list = []
    total_used_bytes = 0.0
    total_bytes_sum = 0.0

    for inst, total_b in total_bytes_map.items():
        avail_b = avail_bytes_map.get(inst)
        if avail_b is None: continue
        used_b = max(0.0, total_b - avail_b)
        usage_ratio = used_b / total_b if total_b > 0 else 0.0
        node_mem_list.append({"node": inst, "usage_percent": usage_ratio * 100.0})
        total_used_bytes += used_b
        total_bytes_sum += total_b

    node_mem_list.sort(key=lambda x: x["usage_percent"], reverse=True)
    mem_top5 = [(n["node"], round(n["usage_percent"], 1)) for n in node_mem_list[:5]]
    total_mem_percent = round((total_used_bytes / total_bytes_sum) * 100.0, 1) if total_bytes_sum > 0 else 0.0
    mem_used_gb = round(total_used_bytes / (1024**3), 1)
    mem_total_gb = round(total_bytes_sum / (1024**3), 1)
    return {"total_mem_percent": total_mem_percent, "mem_used_gb": mem_used_gb, "mem_total_gb": mem_total_gb, "mem_top5": mem_top5}

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = get_user_by_username(username)
        if user and user[2] == password:
            session['username'] = username
            set_last_login(username)
            ensure_gui_pod(username)
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

@app.route("/logout", methods=["POST"])
def logout():
    username = request.form.get("username", None) or session.get("username")
    if username:
        set_last_logout(username)
        session.pop('username', None)
    return render_template("logged_out.html")

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

def _username_sort_key(username: str):
    digits = "".join([c for c in username if c.isdigit()])
    if digits:
        return (int(digits), username)
    return (10**9, username)

@app.route("/admin_dashboard")
def admin_dashboard():
    if not session.get("admin_logged_in"):
        return redirect(url_for('admin_login'))

    try:
        cpu_stats = get_cluster_cpu_usage()
        mem_stats = get_cluster_memory_usage()
        total_cpu_percent = cpu_stats["total_cpu_percent"]
        used_cores = cpu_stats["used_cores"]
        total_cores = cpu_stats["total_cores"]
        cpu_top5 = cpu_stats["cpu_top5"]

        total_mem_percent = mem_stats["total_mem_percent"]
        mem_used_gb = mem_stats["mem_used_gb"]
        mem_total_gb = mem_stats["mem_total_gb"]
        mem_top5 = mem_stats["mem_top5"]
    except Exception:
        total_cpu_percent = 0.0
        used_cores = 0.0
        total_cores = 0
        total_mem_percent = 0.0
        mem_used_gb = 0.0
        mem_total_gb = 0.0
        cpu_top5 = []
        mem_top5 = []

    users = get_all_users()
    users_sorted = sorted(users, key=lambda row: _username_sort_key(row[0]))

    user_status_list = []
    all_accounts_list = []

    for username, last_logout_at, last_login_at, is_logged_in in users_sorted:
        pod_online = check_gui_pod(username)
        status = "ONLINE" if pod_online else "OFFLINE"

        if pod_online and is_logged_in:
            recent_time = "로그인중"
        else:
            if last_logout_at:
                recent_time = to_kst(last_logout_at)
            elif last_login_at:
                recent_time = to_kst(last_login_at)
            else:
                # 최근 접속 이력이 전혀 없는 사용자
                recent_time = "신규 아이디입니다"

        row = {"username": username, "status": status, "recent_time": recent_time}
        user_status_list.append(row)
        all_accounts_list.append(row)

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
        user_status_list=user_status_list,
        all_accounts_list=all_accounts_list
    )

# ---------- 계정관리 액션: 비밀번호 변경 / 계정 삭제 / 신규 생성 / 아이디 중복 확인 ----------

@app.route("/admin_account_change_password", methods=["POST"])
def admin_account_change_password():
    if not session.get("admin_logged_in"):
        return redirect(url_for('admin_login'))
    username = request.form.get("username")
    new_password = request.form.get("new_password")
    new_password_confirm = request.form.get("new_password_confirm")
    if not username or not new_password or not new_password_confirm:
        flash("필수 값이 없습니다.", "danger")
        return redirect(url_for('admin_dashboard') + "#account")
    if new_password != new_password_confirm:
        flash("비밀번호가 일치하지 않습니다.", "danger")
        return redirect(url_for('admin_dashboard') + "#account")

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE users SET password=%s WHERE username=%s", (new_password, username))
        conn.commit()
        flash(f"{username} 비밀번호가 변경되었습니다.", "success")
    except Exception:
        conn.rollback()
        flash("비밀번호 변경 중 오류가 발생했습니다.", "danger")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('admin_dashboard') + "#account")

@app.route("/admin_account_delete", methods=["POST"])
def admin_account_delete():
    if not session.get("admin_logged_in"):
        return redirect(url_for('admin_login'))
    username = request.form.get("username")
    if not username:
        flash("필수 값이 없습니다.", "danger")
        return redirect(url_for('admin_dashboard') + "#account")

    try:
        delete_gui_pod(username)
    except Exception:
        pass

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM users WHERE username=%s", (username,))
        conn.commit()
        flash(f"{username} 계정이 삭제되었습니다.", "success")
    except Exception:
        conn.rollback()
        flash("계정 삭제 중 오류가 발생했습니다.", "danger")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('admin_dashboard') + "#account")

@app.route("/admin_account_check_username", methods=["GET"])
def admin_account_check_username():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    username = request.args.get("username", "").strip()
    if not username:
        return jsonify({"exists": False, "error": "empty username"}), 400
    try:
        exists = username_exists(username)
        return jsonify({"exists": exists})
    except Exception:
        return jsonify({"error": "check failed"}), 500

@app.route("/admin_account_create", methods=["POST"])
def admin_account_create():
    if not session.get("admin_logged_in"):
        return redirect(url_for('admin_login'))
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    password_confirm = request.form.get("password_confirm", "")
    if not username or not password or not password_confirm:
        flash("필수 값이 없습니다.", "danger")
        return redirect(url_for('admin_dashboard') + "#account")
    if password != password_confirm:
        flash("비밀번호가 일치하지 않습니다.", "danger")
        return redirect(url_for('admin_dashboard') + "#account")
    try:
        if username_exists(username):
            flash("이미 존재하는 아이디입니다.", "danger")
            return redirect(url_for('admin_dashboard') + "#account")
        create_user(username, password)
        flash(f"{username} 계정이 생성되었습니다.", "success")
    except Exception:
        flash("계정 생성 중 오류가 발생했습니다.", "danger")
    return redirect(url_for('admin_dashboard') + "#account")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)

