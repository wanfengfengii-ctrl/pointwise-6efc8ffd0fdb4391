from fractions import Fraction


def rate_for(failures, person_time):
    if type(failures) is not int or failures < 0 or person_time < 0:
        raise ValueError('invalid failure totals')
    if person_time == 0:
        if failures:
            raise ValueError('failure without observed time')
        return None
    return Fraction(failures) / person_time


def calculate_rates(totals):
    return {row.stratum: rate_for(row.failures, row.person_time) for row in totals}
