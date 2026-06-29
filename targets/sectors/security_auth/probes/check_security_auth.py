from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


SECRET_RE = re.compile(
    r"(?im)^\s*(?:[A-Z0-9_]*_)?(?:API[_-]?KEY|SECRET|TOKEN|PASSWORD)\s*[:=]\s*['\"]([^'\"\s#]{12,})['\"]"
)


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def add_signal(signals: list[dict[str, object]], bug_class: str, target: Path, line: int, detail: str) -> None:
    signals.append(
        {
            "bug_class": bug_class,
            "path": target.as_posix(),
            "line": line,
            "detail": detail,
        }
    )


def scan_target(target: Path) -> list[dict[str, object]]:
    text = target.read_text(encoding="utf-8")
    lowered = text.lower()
    signals: list[dict[str, object]] = []

    for match in SECRET_RE.finditer(text):
        add_signal(signals, "hardcoded_secret", target, line_number(text, match.start()), "literal credential value")

    cors_patterns = [
        r"access-control-allow-origin['\"]?\s*[:=]\s*['\"]\*['\"]",
        r"allow_origins\s*=\s*\[\s*['\"]\*['\"]\s*\]",
        r"origins?\s*=\s*['\"]\*['\"]",
    ]
    for pattern in cors_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            add_signal(signals, "permissive_cors", target, line_number(text, match.start()), "wildcard CORS origin")
            break

    cookie_match = re.search(r"\bset_cookie\s*\((?P<args>[^)]*)\)", text, flags=re.IGNORECASE | re.DOTALL)
    if cookie_match:
        cookie_args = cookie_match.group("args").lower()
        missing = [name for name in ["httponly", "secure", "samesite"] if name not in cookie_args]
        if missing:
            add_signal(
                signals,
                "insecure_cookie",
                target,
                line_number(text, cookie_match.start()),
                f"cookie missing {','.join(missing)}",
            )
    if "session_cookie_secure = false" in lowered:
        offset = lowered.index("session_cookie_secure = false")
        add_signal(signals, "insecure_cookie", target, line_number(text, offset), "secure session cookies disabled")

    jwt_patterns = [
        r"verify_signature['\"]?\s*:\s*False",
        r"verify_exp['\"]?\s*:\s*False",
        r"algorithms\s*=\s*\[\s*['\"]none['\"]\s*\]",
    ]
    for pattern in jwt_patterns:
        match = re.search(pattern, text)
        if match:
            add_signal(signals, "weak_jwt_validation", target, line_number(text, match.start()), "JWT verification disabled")
            break

    bypass_patterns = [
        r"DEBUG_AUTH_BYPASS\s*=\s*True",
        r"x-debug-user",
        r"return\s+['\"]admin['\"]",
    ]
    if "debug" in lowered and "auth" in lowered:
        for pattern in bypass_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                add_signal(signals, "debug_auth_bypass", target, line_number(text, match.start()), "debug path can grant identity")
                break

    auth_route = any(token in lowered for token in ["/login", "/password-reset", "/reset-password", "password_reset"])
    rate_limit_token = any(token in lowered for token in ["rate_limit", "ratelimit", "limiter", "throttle", "slow_down"])
    if auth_route and not rate_limit_token:
        add_signal(signals, "missing_rate_limit", target, 1, "auth endpoint has no visible throttling guard")

    return signals


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan a small fixture for auth/security risk signals.")
    parser.add_argument("--target", required=True)
    parser.add_argument("--expect", nargs="*", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    target = Path(args.target)
    signals = scan_target(target)
    found_classes = {str(signal["bug_class"]) for signal in signals}

    if args.json:
        print(json.dumps({"target": target.as_posix(), "signals": signals}, indent=2, sort_keys=True))
    else:
        for signal in signals:
            print(f"{signal['bug_class']}:{signal['path']}:{signal['line']}:{signal['detail']}")

    missing = sorted(set(args.expect) - found_classes)
    if missing:
        print(f"missing_expected_security_classes:{','.join(missing)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
