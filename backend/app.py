from flask import Flask, render_template, request, redirect, session
from db import get_db_connection
from kubernetes import client, config
import os

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

# ----------- 관리자 전용 -----------

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
    return render_template("admin_dashboard.html", admin_name=session.get("admin_name", "admin"))

@app.route("/admin_logout", methods=["POST"])
def admin_logout():
    session.pop("admin_logged_in", None)
    session.pop("admin_name", None)
    return redirect("/admin_login")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
