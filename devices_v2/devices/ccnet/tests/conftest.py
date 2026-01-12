"""
Pytest configuration for CCNET tests.
"""

import sys
from pathlib import Path

# Add the devices directory to the path for imports
devices_dir = Path(__file__).parent.parent.parent
if str(devices_dir) not in sys.path:
    sys.path.insert(0, str(devices_dir))
