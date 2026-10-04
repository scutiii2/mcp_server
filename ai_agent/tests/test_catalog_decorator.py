from src.catalog import catalog


def test_bare_decorator_returns_function_unchanged():
    @catalog
    def sample():
        """docstring"""
        return 1

    assert sample() == 1
    assert sample.__doc__ == "docstring"


def test_decorator_with_overrides_returns_function_unchanged():
    @catalog(name="renamed", description="custom")
    def sample():
        return 2

    assert sample() == 2


def test_decorator_on_class_returns_class_unchanged():
    @catalog
    class Sample:
        def __init__(self, x: int):
            self.x = x

    instance = Sample(5)
    assert instance.x == 5
