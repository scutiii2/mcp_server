from src.utils.tokens import generate_otp_code, hash_token, verify_token


def test_generate_otp_code_returns_string_of_requested_length():
    code = generate_otp_code(length=12)

    assert len(code) == 12
    assert code.isascii()


def test_generate_otp_code_is_random():
    first = generate_otp_code()
    second = generate_otp_code()

    assert first != second


def test_hash_token_is_deterministic_and_not_reversible():
    token = "my-secret-code"

    first = hash_token(token)
    second = hash_token(token)

    assert first == second
    assert first != token
    assert len(first) == 64


def test_verify_token_true_for_matching_token():
    token = "my-secret-code"
    token_hash = hash_token(token)

    assert verify_token(token, token_hash) is True


def test_verify_token_false_for_wrong_token():
    token_hash = hash_token("my-secret-code")

    assert verify_token("wrong-code", token_hash) is False
