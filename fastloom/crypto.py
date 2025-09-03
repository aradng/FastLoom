import secrets


def generate_token(length: int):
    """
    Generates a n-digits numeral token, that used for OTP
    """
    min_value = 10 ** (length - 1)
    max_value = 10**length - 1
    return str(secrets.randbelow(max_value - min_value + 1) + min_value).zfill(
        length
    )


def generate_alphanumeric_token(length: int):
    """
    Generates a n-digits alphanumeric token, that used for OTP
    """
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    return "".join(secrets.choice(alphabet) for _ in range(length))
