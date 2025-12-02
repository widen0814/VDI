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
    # 기존 pod 있으면 skip (동일 user 라벨)
    pods = v1.list_namespaced_pod(namespace=namespace, label_selector=f"user={user}")
    if len(pods.items) > 0:
        # POD 정상 떠 있다고 가정: 같은 노드포트로 연결
        return pod_name, "EXISTS", "http://192.168.2.111:30680/?resize=scale"

    # 새로운 pod manifest (Istio injection off, VNC auth off)
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
                "image": "accetto/ubuntu-vnc-xfce",
                "env": [{"name": "VNC_DISABLE_AUTH", "value": "true"}],
                "ports": [{"containerPort": 6080}, {"containerPort": 5901}]
            }]
        }
    }
    v1.create_namespaced_pod(namespace=namespace, body=pod_manifest)
    return pod_name, "CREATED", "http://192.168.2.111:30680/?resize=scale"

def delete_gui_pod(user):
    config.load_kube_config()
    namespace = "default"
    pod_name = f"gui-{user}"

    v1 = client.CoreV1Api()
    try:
        v1.delete_namespaced_pod(name=pod_name, namespace=namespace)
    except Exception as e:
        pass # 이미 사라진 경우 무시

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
            # 로그인 성공시 바로 GUI로 리다이렉트!
            return redirect(gui_url)
        else:
            message = "로그인 실패"
            return render_template("login.html", message=message)
    return render_template("login.html")

@app.route("/logout", methods=["POST"])
def logout():
    username = request.form.get("username", None) or session.get("username")
    if username:
        delete_gui_pod(username)
        session.pop('username', None)
    return redirect("/")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
