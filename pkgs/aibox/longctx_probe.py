#!/usr/bin/env python3
"""Long-context acceptance probe for the AI Box (stdlib only, runs in the offline coding container).

  aibox exec PROJECT -- python3 /share/aibox/longctx_probe.py --tokens 200000

Checks: needle retrieval at several depths, streaming speed and MTP statistics,
tool calling, and a generated image. Prints a JSON report; exit code 1 on any failure.
Results are only meaningful on the real RX 6800 with the server started by aibox.
"""
import argparse
import base64
import json
import struct
import sys
import time
import urllib.request
import zlib

BASE = "http://strata:8080"


def post(path, body, stream=False, timeout=3600):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


def chat(messages, **extra):
    body = {"model": "local", "messages": messages, "temperature": 0, **extra}
    started = time.monotonic()
    with post("/v1/chat/completions", body) as response:
        data = json.load(response)
    data["_seconds"] = time.monotonic() - started
    return data


def stream_speed(prompt, max_tokens=256):
    body = {"model": "local", "stream": True, "max_tokens": max_tokens, "temperature": 0,
            "stream_options": {"include_usage": True}, "messages": [{"role": "user", "content": prompt}]}
    started, first, count, usage = time.monotonic(), None, 0, {}
    with post("/v1/chat/completions", body) as response:
        for raw in response:
            line = raw.decode().strip()
            if not line.startswith("data:") or line.endswith("[DONE]"):
                continue
            event = json.loads(line[5:])
            usage = event.get("usage") or usage
            if event.get("kvmem"):
                usage = {**usage, "kvmem": event["kvmem"]}
            for choice in event.get("choices", []):
                delta = choice.get("delta", {})
                if delta.get("content") or delta.get("reasoning_content"):
                    first = first or time.monotonic()
                    count += 1
    end = time.monotonic()
    return {"ttft_s": round((first or end) - started, 2),
            "decode_chunks_per_s": round(count / max(end - (first or started), 1e-6), 2),
            "usage": usage}


def png(width, height, left, right):
    row = b"\x00" + (bytes(left) * (width // 2) + bytes(right) * (width - width // 2))
    raw = zlib.compress(row * height)
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


def filler(tokens):
    # ~1.3 tokens per word of varied, needle-free log-like prose
    words = []
    for i in range(int(tokens / 1.3 / 9)):
        words.append(f"Entry {i}: service node{i % 97} reported status {(i * 7) % 13} after retry {(i * 3) % 5}.")
    return "\n".join(words)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tokens", type=int, default=32000, help="approximate prompt size for retrieval/speed")
    parser.add_argument("--depths", default="0.05,0.5,0.95")
    parser.add_argument("--skip", default="", help="comma list: retrieval,speed,tools,vision")
    args = parser.parse_args()
    skip = set(filter(None, args.skip.split(",")))
    report, failed = {"requested_tokens": args.tokens}, False
    health = json.load(urllib.request.urlopen(BASE + "/health", timeout=10))
    report["health"] = health
    if "retrieval" not in skip:
        results = []
        text = filler(args.tokens).split("\n")
        for depth in map(float, args.depths.split(",")):
            code = f"VX-{int(depth * 1000):04d}-{abs(hash(depth)) % 9000 + 1000}"
            lines = list(text)
            lines.insert(int(len(lines) * depth), f"IMPORTANT: the maintenance passphrase is {code}.")
            data = chat([{"role": "user", "content": "\n".join(lines) + "\n\nWhat is the maintenance passphrase? Answer with the code only."}], max_tokens=64)
            ok = code in json.dumps(data["choices"][0]["message"])
            failed |= not ok
            results.append({"depth": depth, "expected": code, "ok": ok, "seconds": round(data["_seconds"], 1),
                            "prompt_tokens": data.get("usage", {}).get("prompt_tokens")})
        report["retrieval"] = results
    if "speed" not in skip:
        report["speed"] = stream_speed(filler(args.tokens) + "\n\nSummarize the log above in three sentences.")
    if "tools" not in skip:
        tool = {"type": "function", "function": {"name": "write_file", "description": "Write a file",
                "parameters": {"type": "object", "required": ["path", "content"],
                               "properties": {"path": {"type": "string"}, "content": {"type": "string"}}}}}
        data = chat([{"role": "user", "content": "Create hello.py that prints 'hi' using the write_file tool."}],
                    tools=[tool], tool_choice="auto", max_tokens=512)
        calls = data["choices"][0]["message"].get("tool_calls") or []
        ok = bool(calls) and calls[0]["function"]["name"] == "write_file" and "path" in json.loads(calls[0]["function"]["arguments"])
        failed |= not ok
        report["tools"] = {"ok": ok, "calls": len(calls)}
    if "vision" not in skip:
        image = "data:image/png;base64," + base64.b64encode(png(256, 128, (255, 0, 0), (0, 0, 255))).decode()
        data = chat([{"role": "user", "content": [{"type": "image_url", "image_url": {"url": image}},
                      {"type": "text", "text": "Name the colour of the left half and of the right half."}]}], max_tokens=128)
        answer = json.dumps(data["choices"][0]["message"]).lower()
        ok = "red" in answer and "blue" in answer
        failed |= not ok
        report["vision"] = {"ok": ok, "answer": data["choices"][0]["message"].get("content")}
    print(json.dumps(report, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
