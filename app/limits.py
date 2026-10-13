import math

# Integers exchanged with the browser must retain their exact value in JavaScript.
MAX_SAFE_INTEGER = 2**53 - 1


def integer(value, label, minimum=1):
    if type(value) is not int or not minimum <= value <= MAX_SAFE_INTEGER:
        raise ValueError(f'{label}: укажите целое число не меньше {minimum}')
    return value


def finite_number(value, label, minimum=0, maximum=None):
    if type(value) not in (int, float) or not minimum <= value <= MAX_SAFE_INTEGER or not math.isfinite(value) or (maximum is not None and value > maximum):
        raise ValueError(f'{label}: недопустимое число')
    return value
