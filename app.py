from flask import Flask, render_template, request
from db import get_db_connection
from kubernetes import client, config
import os

app = Flask(__name__)

def ensure_gui_pod(user):
    config.load_kube_config()
    namespace = "default"
    pod_name = f"gui-{user}"

    v1 = client.CoreV1Api()
    pods = v1.list_namespaced_pod(namespace=namespace, label_selector=f"user={user}")
    if len(pods.items) > 0:
        return pod_name, "EXISTS", f"http://192.168.2.111:38080/?resize=scale"

    pod_manifest = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": pod_name,
            "labels": {"user": user}
        },
        "spec": {
            "containers": [{
                "name": "gui",
                "image": "dorowu/ubuntu-desktop-lxde-vnc",
                "ports": [{"containerPort": 80}, {"containerPort": 5901}],
                "env": [
                    {"name": "VNC_PASSWORD", "value": "1234"}
                ]
            }]
        }
    }
    v1.create_namespaced_pod(namespace=namespace, body=pod_manifest)
    return pod_name, "CREATED", f"http://192.168.2.111:38080/?resize=scale"

@app.route("/", methods=["GET", "POST"])
def login():
    message = ""
    gui_url = ""
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
            pod, status, gui_url = ensure_gui_pod(username)
            message = f"로그인 성공, GUI POD 상태: {status}"
        else:
            message = "로그인 실패"
    return render_template("login.html", message=message, gui_url=gui_url)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
