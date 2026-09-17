import botocore
import numpy
import pandas


def test_core_dependencies_are_importable() -> None:
    assert botocore.__version__
    assert numpy.__version__
    assert pandas.__version__
