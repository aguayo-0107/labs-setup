"""Python package parity between two Docker images.

The Spark Driver runs in the spark-jupyter image and the Executors run the
environment packed from spark-job-venv. When both have the same distribution
installed at different versions, the Driver and the Workers can compute
different results from the same code, so the infrastructure notebook stops.
"""

from .composition import check_python_parity
from .domain.errors import EnvironmentsDiffer
from .domain.models import PythonEnvironment, VersionDifference

__all__ = ["EnvironmentsDiffer", "PythonEnvironment", "VersionDifference", "check_python_parity"]
