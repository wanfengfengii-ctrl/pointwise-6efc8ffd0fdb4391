def count_failures(prepared):
    counts = {key: 0 for key in prepared.strata}
    for member in prepared.members:
        if member.intervals and member.intervals[-1].failed:
            counts[member.stratum] += 1
    return counts
