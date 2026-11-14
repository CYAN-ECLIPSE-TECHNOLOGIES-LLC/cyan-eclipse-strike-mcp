#!/usr/bin/env python3
"""K4 house-refusal regression test (ETO-53/54/55, WS-5 sweep-cure).

Forced-failure probe over real stdio: malformed JSON, a non-object
request, and a tools/call whose params are the wrong type must never
produce a -32603, a raw exception string, an exception class name, or
a dead process. The server must still answer a later initialize.
Run: python3 tests/test_k4_house_refusal.py  (exit 0 = pass)
"""
import json, subprocess, sys, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CMD = [sys.executable, os.path.join(ROOT, "server.py")]
LEAKS = ["-32603", "Traceback", "AttributeError", "TypeError",
         "KeyError", "ValueError", "IndexError", "RuntimeError"]

LINES = [
    "this is not json",
    "[]",
    json.dumps({"jsonrpc": "2.0", "id": 99, "method": "tools/call",
                "params": "boom-not-a-dict"}),
    json.dumps({"jsonrpc": "2.0", "id": 100, "method": "initialize",
                "params": {}}),
]


def main():
    proc = subprocess.Popen(CMD, cwd=ROOT, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True)
    try:
        out, _ = proc.communicate("\n".join(LINES) + "\n", timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        print("FAIL: server hung on malformed input")
        return 1
    for leak in LEAKS:
        if leak in out:
            print(f"FAIL: leaked {leak!r} in output: {out[:400]}")
            return 1
    answered = False
    for line in out.splitlines():
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("id") == 100 and "result" in obj:
            answered = True
    if not answered:
        print(f"FAIL: server did not answer initialize after faults: {out[:400]}")
        return 1
    print("PASS: faults refused by name, no raw leak, server alive")
    return 0


if __name__ == "__main__":
    sys.exit(main())
