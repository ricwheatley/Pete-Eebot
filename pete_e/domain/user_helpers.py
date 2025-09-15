from datetime import date
from typing import Optional

def calculate_age(birth_date: date, on_date: Optional[date] = None) -> int:
    """Calculates age based on a birth date, as of a specific date."""
    # If no specific date is given, use today's date
    if on_date is None:
        on_date = date.today()

    age = on_date.year - birth_date.year - ((on_date.month, on_date.day) < (birth_date.month, birth_date.day))
    return age