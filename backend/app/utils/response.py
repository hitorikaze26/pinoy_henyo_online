from flask import jsonify


def success_response(data=None, message=None, status=200):
    body = {"success": True, "data": data if data is not None else {}}
    if message is not None:
        body["message"] = message
    return jsonify(body), status


def error_response(message, code="INTERNAL_ERROR", status=500, **extra):
    error = {"code": code, "message": message}
    if extra:
        error.update(extra)
    body = {"success": False, "error": error}
    return jsonify(body), status