import json
import subprocess
import sys

binary = sys.argv[1]
process = subprocess.Popen(
    [binary, "app-server", "--stdio"],
    text=True,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    bufsize=1,
)

def send(message):
    process.stdin.write(json.dumps(message) + "\n")
    process.stdin.flush()

def receive(request_id):
    while True:
        line = process.stdout.readline()
        if not line:
            raise RuntimeError("app-server closed before responding")
        message = json.loads(line)
        if message.get("id") == request_id:
            return message

send({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "session-rescue-probe", "version": "0.1.0"}}})
print(json.dumps(receive(1)))
send({"method": "initialized", "params": {}})
send({"id": 2, "method": "thread/list", "params": {"archived": True, "limit": 5, "sortKey": "updated_at", "sortDirection": "desc"}})
print(json.dumps(receive(2)))
process.terminate()
process.wait(timeout=5)
