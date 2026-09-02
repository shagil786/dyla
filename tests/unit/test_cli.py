from dyla.cli import app


def test_console_entry_point_is_importable():
    assert callable(app)
