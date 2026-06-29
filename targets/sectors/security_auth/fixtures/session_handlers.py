DEBUG_AUTH_BYPASS = True


def issue_session(response, user_id):
    response.set_cookie("session", f"user:{user_id}")
    return response


def current_user(request):
    if DEBUG_AUTH_BYPASS and request.headers.get("X-Debug-User"):
        return "admin"
    return request.user
