# Security/Auth Sector

This sector covers static security and authentication defects that appear in common business repositories before a service is deployed: hardcoded credentials, permissive CORS, missing cookie flags, weak JWT validation, debug auth bypasses, and unthrottled authentication endpoints.

The fixtures are dependency-free Python/text targets. A small stdlib probe scans each fixture and emits normalized bug-class tokens, so `buglab sector` can score the pack with the existing command runner.

Manifest: `targets/sectors/security_auth/manifest.json`

| Fixture | Target | Expected classes | Minimum |
| --- | --- | --- | ---: |
| Static secret and CORS | `targets/sectors/security_auth/fixtures/service_config.py` | hardcoded secret, permissive CORS | 2 |
| Session cookie debug bypass | `targets/sectors/security_auth/fixtures/session_handlers.py` | insecure cookie, debug auth bypass | 2 |
| Weak JWT gateway | `targets/sectors/security_auth/fixtures/jwt_gateway.py` | weak JWT validation, hardcoded secret | 2 |
| Password reset without throttle | `targets/sectors/security_auth/fixtures/password_reset.py` | missing rate limit, permissive CORS | 2 |

Run:

```powershell
python -m buglab sector --repo . --manifest targets\sectors\security_auth\manifest.json --loops 1 --name security_auth_verify
```

The probe emits one line per detected class, such as `hardcoded_secret:<path>:<line>:<detail>`. The manifest lists those class tokens under `forbidden_stdout` so the existing command runner treats each emitted finding as a deterministic sector signal.

Expected signals:

- `hardcoded_secret` for literal API keys, JWT secrets, tokens, passwords, or similar credential values.
- `permissive_cors` for wildcard CORS origins.
- `insecure_cookie` for session cookies missing `httponly`, `secure`, or `samesite`, or explicit secure-cookie disablement.
- `weak_jwt_validation` for disabled JWT signature/expiry checks or `none` algorithms.
- `debug_auth_bypass` for debug-only auth paths that can grant a user identity.
- `missing_rate_limit` for login or password-reset style endpoints without visible throttling guards.
