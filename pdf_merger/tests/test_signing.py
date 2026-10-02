from __future__ import annotations

from src.store.signing import LinkSigner


def test_sign_and_verify():
    clock = lambda: 1000.0  # noqa: E731
    signer = LinkSigner(b"k" * 32, ttl_seconds=60, clock=clock)

    exp, sig = signer.sign("f_" + "a" * 32)

    assert exp == 1060
    assert signer.verify("f_" + "a" * 32, exp, sig)
    assert not signer.verify("f_" + "b" * 32, exp, sig)
    assert not signer.verify("f_" + "a" * 32, exp + 1, sig)
    assert not signer.verify("f_" + "a" * 32, exp, "0" * 64)


def test_expired_link_fails():
    now = [1000.0]
    signer = LinkSigner(b"k" * 32, ttl_seconds=60, clock=lambda: now[0])
    exp, sig = signer.sign("f_" + "a" * 32)

    now[0] = 1061.0

    assert not signer.verify("f_" + "a" * 32, exp, sig)
