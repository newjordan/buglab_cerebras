JWT_SECRET = "temporary-jwt-secret"


def decode_partner_token(jwt, token):
    return jwt.decode(
        token,
        JWT_SECRET,
        algorithms=["none"],
        options={"verify_signature": False, "verify_exp": False},
    )
