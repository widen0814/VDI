from flask import Flask, render_template, request, redirect, session
from db import get_db_connection
from kubernetes import client, config
import operator
import requests

app = Flask(__name__)
app.secret_key = "super-secret-key-123"

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
    except Exception as e:
        pass

PROMETHEUS_URL = "http://192.168.2.111:30900"

def query_prometheus(query):
    try:
        response = requests.get(f"{PROMETHEUS_URL}/api/v1/query", params={'query': query}, timeout=4)
        result = response.json()
        if result['status'] == 'success':
            return result['data']['result']
    except Exception as e:
        print("Prometheus query error:", e)
    return []

def get_node_cpu_percent():
    cpu_query = '100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[2m])) by (instance))'
    cpu_data = query_prometheus(cpu_query)
    percent_dict = {}
    for item in cpu_data:
        node = item["metric"].get("instance", "unknown")
        value = float(item["value"][1])
        percent_dict[node] = value
    return percent_dict

def get_node_mem_percent():
    mem_total_query     = 'node_memory_MemTotal_bytes'
    mem_free_query      = 'node_memory_MemFree_bytes'
    mem_buffers_query   = 'node_memory_Buffers_bytes'
    mem_cached_query    = 'node_memory_Cached_bytes'
    mem_sreclaim_query  = 'node_memory_SReclaimable_bytes'

    total_data    = query_prometheus(mem_total_query)
    free_data     = query_prometheus(mem_free_query)
    buffers_data  = query_prometheus(mem_buffers_query)
    cached_data   = query_prometheus(mem_cached_query)
    sreclaim_data = query_prometheus(mem_sreclaim_query)

    percent_dict = {}
    for item in total_data:
        node = item["metric"].get("instance", "unknown")
        total    = float(item["value"][1])
        free     = float(next((i["value"][1] for i in free_data if i["metric"].get("instance", "") == node), 0))
        buffers  = float(next((i["value"][1] for i in buffers_data if i["metric"].get("instance", "") == node), 0))
        cached   = float(next((i["value"][1] for i in cached_data if i["metric"].get("instance", "") == node), 0))
        sreclaim = float(next((i["value"][1] for i in sreclaim_data if i["metric"].get("instance", "") == node), 0))
        used = total - (free + buffers + cached + sreclaim)
        used_percent = (used / total) * 100 if total > 0 else 0
        percent_dict[node] = used_percent
    return percent_dict

def get_node_mem_used_total_bytes():
    # Returns two dicts: used_bytes and total_bytes per node
    mem_total_query     = 'node_memory_MemTotal_bytes'
    mem_free_query      = 'node_memory_MemFree_bytes'
    mem_buffers_query   = 'node_memory_Buffers_bytes'
    mem_cached_query    = 'node_memory_Cached_bytes'
    mem_sreclaim_query  = 'node_memory_SReclaimable_bytes'

    total_data    = query_prometheus(mem_total_query)
    free_data     = query_prometheus(mem_free_query)
    buffers_data  = query_prometheus(mem_buffers_query)
    cached_data   = query_prometheus(mem_cached_query)
    sreclaim_data = query_prometheus(mem_sreclaim_query)

    used_bytes_dict = {}
    total_bytes_dict = {}
    for item in total_data:
        node = item["metric"].get("instance", "unknown")
        total    = float(item["value"][1])
        free     = float(next((i["value"][1] for i in free_data if i["metric"].get("instance", "") == node), 0))
        buffers  = float(next((i["value"][1] for i in buffers_data if i["metric"].get("instance", "") == node), 0))
        cached   = float(next((i["value"][1] for i in cached_data if i["metric"].get("instance", "") == node), 0))
        sreclaim = float(next((i["value"][1] for i in sreclaim_data if i["metric"].get("instance", "") == node), 0))
        used = total - (free + buffers + cached + sreclaim)
        used_bytes_dict[node] = used
        total_bytes_dict[node] = total
    return used_bytes_dict, total_bytes_dict

def get_node_name_map():
    config.load_kube_config()
    v1 = client.CoreV1Api()
    nodes = v1.list_node()
    node_map = {}
    node_core_count = {}
    for node in nodes.items:
        node_name = node.metadata.name
        core_count = 0
        for cap_k, cap_v in node.status.capacity.items():
            if cap_k == "cpu":
                try:
                    core_count = int(cap_v)
                except:
                    if "m" in cap_v:
                        core_count = int(cap_v.replace("m", "")) / 1000
            elif cap_k == "allocatable":
                continue
        node_core_count[node_name] = core_count
        for address in node.status.addresses:
            if address.type == "InternalIP":
                node_map[address.address + ":9100"] = node_name
    return node_map, node_core_count

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username=%s AND password=%s", (username, password))
        user = cur.fetchone()
        cur.close()
        conn.close()
        if user:
            session['username'] = username
            pod, status, gui_url = ensure_gui_pod(username)
            return render_template("waiting.html", gui_url="/desktop")
        else:
            message = "로그인 실패"
            return render_template("login.html", message=message)
    return render_template("login.html")

@app.route("/desktop")
def desktop():
    username = session.get('username')
    if not username:
        return redirect("/")
    gui_url = "http://192.168.2.111:30680/"
    return render_template("desktop.html", gui_url=gui_url, username=username)

@app.route("/logout", methods=["POST"])
def logout():
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
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM admins WHERE username=%s AND password=%s", (username, password))
        admin = cur.fetchone()
        cur.close()
        conn.close()
        if admin:
            session['admin_logged_in'] = True
            session['admin_name'] = username
            return redirect("/admin_dashboard")
        else:
            message = "로그인 실패"
            return render_template("admin_login.html", message=message)
    return render_template("admin_login.html")

@app.route("/admin_dashboard")
def admin_dashboard():
    if not session.get("admin_logged_in"):
        return redirect("/admin_login")

    cpu_by_node = get_node_cpu_percent()
    mem_by_node = get_node_mem_percent()
    node_name_map, node_core_count = get_node_name_map()

    # 모든 노드명 리스트 (k8s에서 수집한 노드 전체)
    all_node_names = list(node_core_count.keys())

    # Prometheus값(node-exporter)와 합산
    cpu_by_name = {node_name_map.get(ip, ip): percent for ip, percent in cpu_by_node.items()}
    mem_by_name = {node_name_map.get(ip, ip): percent for ip, percent in mem_by_node.items()}

    cpu_by_name_full = {name: cpu_by_name.get(name, 0) for name in all_node_names}
    mem_by_name_full = {name: mem_by_name.get(name, 0) for name in all_node_names}

    used_cores = 0
    total_cores = 0
    for node_name in all_node_names:
        percent = cpu_by_name_full[node_name]
        core = node_core_count.get(node_name, 0)
        used_cores += core * percent / 100
        total_cores += core
    total_cpu_percent = (used_cores / total_cores) * 100 if total_cores > 0 else 0

    cpu_top5 = sorted(cpu_by_name_full.items(), key=operator.itemgetter(1), reverse=True)[:5]
    mem_top5 = sorted(mem_by_name_full.items(), key=operator.itemgetter(1), reverse=True)[:5]

    total_mem_percent = (sum(mem_by_name_full.values()) / len(mem_by_name_full.values())) if mem_by_name_full else 0

    # 메모리 Used/Total GB 계산
    mem_used_dict, mem_total_dict = get_node_mem_used_total_bytes()
    mem_used_gb = sum(mem_used_dict.values()) / 1024 / 1024 / 1024 if mem_used_dict else 0
    mem_total_gb = sum(mem_total_dict.values()) / 1024 / 1024 / 1024 if mem_total_dict else 0

    return render_template("admin_dashboard.html",
        admin_name=session.get("admin_name", "admin"),
        cpu_by_name=cpu_by_name_full,
        mem_by_name=mem_by_name_full,
        node_core_count=node_core_count,
        total_cpu_percent=total_cpu_percent,
        used_cores=used_cores,
        total_cores=total_cores,
        cpu_top5=cpu_top5,
        mem_top5=mem_top5,
        total_mem_percent=total_mem_percent,
        mem_used_gb=mem_used_gb,
        mem_total_gb=mem_total_gb
    )

@app.route("/admin_logout", methods=["POST"])
def admin_logout():
    session.pop("admin_logged_in", None)
    session.pop("admin_name", None)
    return redirect("/admin_login")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
