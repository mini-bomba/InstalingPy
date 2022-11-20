class LoginError(Exception):
    """
    Could not log in
    """
    pass


class SessionExpired(Exception):
    """
    Session expired
    """
    pass
