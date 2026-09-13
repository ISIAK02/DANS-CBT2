import importlib
import json
import mimetypes
import os
import sys
from urllib.parse import parse_qs


API_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
if API_DIRECTORY not in sys.path:
    sys.path.insert(0, API_DIRECTORY)


ROUTES = {
    "/api/config": "config",
    "/api/payments": "payments",
    "/api/subscriptions": "subscriptions",
    "/api/documents": "documents",
    "/api/exams": "exams",
    "/api/videos": "videos",
    "/api/leaderboard": "leaderboard",
    "/api/profile": "profile",
    "/api/analytics": "analytics",
    "/api/user-analytics": "user_analytics",
    "/api/notifications": "notifications",
}


def _event(environ):
    length = int(environ.get("CONTENT_LENGTH") or 0)
    raw_body = environ["wsgi.input"].read(length) if length else b""
    headers = {
        key[5:].lower().replace("_", "-"): value
        for key, value in environ.items()
        if key.startswith("HTTP_")
    }
    return {
        "httpMethod": environ.get("REQUEST_METHOD", "GET"),
        "headers": headers,
        "body": raw_body.decode("utf-8") if raw_body else "{}",
        "path": environ.get("PATH_INFO", "/"),
    }


def application(environ, start_response):
    path = environ.get("PATH_INFO", "/").rstrip("/") or "/"
    if not path.startswith("/api/"):
        relative_path = "index.html" if path == "/" else path.lstrip("/")
        project_root = os.path.dirname(API_DIRECTORY)
        file_path = os.path.abspath(os.path.join(project_root, relative_path))
        if file_path.startswith(project_root + os.sep) and os.path.isfile(file_path):
            with open(file_path, "rb") as static_file:
                content = static_file.read()
            content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
            start_response("200 OK", [("Content-Type", content_type), ("Content-Length", str(len(content)))])
            return [content]
        result = {"statusCode": 404, "headers": {"Content-Type": "text/plain"}, "body": "Not found"}
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [result["body"].encode("utf-8")]
    module_name = ROUTES.get(path)
    if not module_name:
        result = {"statusCode": 404, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"error": "Not found"})}
    else:
        try:
            module = importlib.import_module(module_name)
            result = module.handler(_event(environ))
        except Exception:
            result = {"statusCode": 500, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"error": "The request could not be completed."})}
    status = int(result.get("statusCode", 200))
    headers = [(key, value) for key, value in result.get("headers", {}).items()]
    body = result.get("body", "")
    if not isinstance(body, bytes):
        body = body.encode("utf-8")
    start_response(f"{status} {'OK' if status < 400 else 'Error'}", headers)
    return [body]


app = application