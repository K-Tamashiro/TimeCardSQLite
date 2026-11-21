"""Display formatting for durations."""


def fmt(m):
    return "—" if m is None else "%d:%02d / %.2fh" % (m // 60, m % 60, m / 60)


def dual(m):
    if m is None:
        return "—"
    return (
        '<div class="duration"><strong>%d:%02d</strong><small>%.2fh</small></div>'
        % (m // 60, m % 60, m / 60)
    )
