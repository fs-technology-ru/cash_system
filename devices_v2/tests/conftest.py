"""
Pytest configuration for cash system tests.

This conftest.py adds the devices_v2 directory to sys.path
so that tests can import modules properly.
"""

import sys
from pathlib import Path


# Add the devices_v2 directory to sys.path for proper imports
devices_v2_path = Path(__file__).parent.parent
if str(devices_v2_path) not in sys.path:
    sys.path.insert(0, str(devices_v2_path))
