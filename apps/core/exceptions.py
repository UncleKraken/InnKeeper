class BusinessError(Exception):
    """A rule of the business was broken (e.g. checking out with an unpaid balance).

    The message is safe to show to staff.
    """
