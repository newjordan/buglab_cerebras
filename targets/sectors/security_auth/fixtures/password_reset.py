def password_reset(request, mailer):
    if request.path == "/password-reset" and request.method == "POST":
        user_email = request.form["email"]
        mailer.send_reset_link(user_email)
        return {"ok": True}
    return {"ok": False}


def cors_headers():
    return {"Access-Control-Allow-Origin": "*"}
