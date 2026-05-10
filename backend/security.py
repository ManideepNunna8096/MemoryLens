import re


EMAIL_RE = re.compile(r'^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$', re.IGNORECASE)


def is_valid_email(email):
    return bool(EMAIL_RE.match((email or '').strip()))


def validate_password_strength(password):
    if len(password) < 8:
        return False, 'Password must be at least 8 characters'
    if not re.search(r'[A-Z]', password):
        return False, 'Password must include at least one uppercase letter'
    if not re.search(r'[a-z]', password):
        return False, 'Password must include at least one lowercase letter'
    if not re.search(r'\d', password):
        return False, 'Password must include at least one number'
    return True, None
