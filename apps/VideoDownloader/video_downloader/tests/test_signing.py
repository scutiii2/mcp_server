from src.store.signing import LinkSigner


def test_sign_and_verify_roundtrip():
    now = [1000.0]
    signer = LinkSigner(b"k" * 32, 3600, clock=lambda: now[0])
    exp, sig = signer.sign("f_1")
    assert exp == 4600
    assert signer.verify("f_1", exp, sig)


def test_rejects_other_file_tampered_sig_and_expiry():
    now = [1000.0]
    signer = LinkSigner(b"k" * 32, 60, clock=lambda: now[0])
    exp, sig = signer.sign("f_1")
    assert not signer.verify("f_2", exp, sig)
    assert not signer.verify("f_1", exp, sig[:-1] + ("0" if sig[-1] != "0" else "1"))
    assert not signer.verify("f_1", exp + 1, sig)
    now[0] = exp + 1
    assert not signer.verify("f_1", exp, sig)
