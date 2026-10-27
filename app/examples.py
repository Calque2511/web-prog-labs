def validate_email(email: str) -> bool:
    if "@" not in email:
        return False
    parts = email.split("@")
    if len(parts) != 2:
        return False
    local, domain = parts
    if not local or not domain:
        return False
    return "." in domain


def calculate_discount(price: float, discount_percent: float) -> float:
    if price < 0 or not 0 <= discount_percent <= 100:
        raise ValueError("price must be >= 0 and discount between 0 and 100")
    return price - price * discount_percent / 100


def divide(a: float, b: float) -> float:
    if b == 0:
        raise ValueError("Division by zero")
    return a / b
