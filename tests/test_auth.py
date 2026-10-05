import hashlib
import hmac

import server


def sign(body, secret):
    return "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()


def test_valid_signature_is_accepted():
    server.secret = b"test-secret"
    body = b'{"zen": "hello"}'
    assert server.auth_is_valid(sign(body, server.secret), body)


def test_wrong_signature_is_rejected():
    server.secret = b"test-secret"
    body = b'{"zen": "hello"}'
    assert not server.auth_is_valid(sign(body, b"other-secret"), body)


def test_wrong_signature_is_rejected_even_in_debug_mode():
    # app.debug used to make auth_is_valid return True unconditionally, so any
    # deployment started with debug mode on skipped webhook signature
    # verification entirely.
    server.secret = b"test-secret"
    server.app.debug = True
    try:
        body = b'{"zen": "hello"}'
        assert not server.auth_is_valid(sign(body, b"other-secret"), body)
    finally:
        server.app.debug = False
