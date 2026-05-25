from __future__ import annotations

import queue
import threading
import time
import uuid
from flask import Flask, jsonify, request, Response

from src.ops_service import OpsRuntime, Task, ToolRegistry

app = Flask(__name__)
runtime = OpsRuntime()
registry = ToolRegistry(runtime)
tasks: dict[str, Task] = {}


def _run_task(task_id: str, tool_name: str, payload: dict):
    t = tasks[task_id]
    t.status = "running"
    t.updated_at = time.time()
    runtime.emit("task_status", {"task_id": task_id, "status": t.status})
    try:
        result = registry.tools[tool_name](payload)
        t.result = result
        t.status = "completed"
    except Exception as exc:
        t.result = {"error": str(exc)}
        t.status = "failed"
    t.updated_at = time.time()
    runtime.emit("task_status", {"task_id": task_id, "status": t.status})


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.post("/tasks")
def create_task():
    body = request.get_json(force=True)
    tool_name = body.get("tool")
    payload = body.get("payload", {})
    if tool_name not in registry.tools:
        return jsonify({"error": "unknown tool"}), 400
    task_id = str(uuid.uuid4())
    now = time.time()
    task = Task(id=task_id, name=tool_name, status="queued", created_at=now, updated_at=now, payload=payload)
    tasks[task_id] = task
    threading.Thread(target=_run_task, args=(task_id, tool_name, payload), daemon=True).start()
    return jsonify({"task_id": task_id})


@app.get("/tasks")
def list_tasks():
    return jsonify([t.__dict__ for t in sorted(tasks.values(), key=lambda x: x.created_at, reverse=True)])


@app.get("/tasks/<task_id>")
def get_task(task_id: str):
    t = tasks.get(task_id)
    if not t:
        return jsonify({"error": "not found"}), 404
    return jsonify(t.__dict__)


@app.get("/events")
def events():
    def gen():
        while True:
            try:
                evt = runtime.events.get(timeout=20)
                yield f"data: {evt}\n\n"
            except queue.Empty:
                yield "event: ping\ndata: {}\n\n"
    return Response(gen(), mimetype="text/event-stream")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8765, debug=False)
