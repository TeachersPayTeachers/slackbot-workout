import exercise
from freezegun import freeze_time


def test_save_user_time():
    """
    Freeze Times are UTC Time
    """

    with freeze_time("2012-01-01 10:00:00"):
        assert exercise.save_user_time() == False

    with freeze_time("2012-01-01 22:00:00"):
        assert exercise.save_user_time() == True

    with freeze_time("2012-01-01 22:00:01"):
        assert exercise.save_user_time() == False
