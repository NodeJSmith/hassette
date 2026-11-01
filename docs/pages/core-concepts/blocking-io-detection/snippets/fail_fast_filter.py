import warnings

from hassette import HassetteBlockingIOWarning

warnings.filterwarnings("error", category=HassetteBlockingIOWarning)
