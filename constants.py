"""Constants used throughout the CAN Frame Simulation application.

This module centralizes all constants used in the application to improve maintainability
and avoid magic numbers scattered throughout the codebase.
"""

# CAN Frame Constants
CAN_FRAME_MAX_DATA_LENGTH = 8
CAN_STANDARD_ID_MAX = 0x7FF  # 11-bit max value
CAN_EXTENDED_ID_MAX = 0x1FFFFFFF  # 29-bit max value

# CAN ID Constants
DEVICE_A_STATUS_ID = 0x18FF0001
DEVICE_B_STATUS_ID = 0x18FF0002
WATCHDOG_FRAME_ID = 0x100
CONTROL_FRAME_ID = 0x200

# Device Operational Values
DEVICE_A_OP_VALUE_1 = 1
DEVICE_A_OP_VALUE_2 = 2
DEVICE_A_OP_VALUE_3 = 3

# Module C Operational Multipliers
MODULE_C_MULTIPLIER_1 = 1
MODULE_C_MULTIPLIER_10 = 10
MODULE_C_MULTIPLIER_100 = 100
MODULE_C_MULTIPLIER_1000 = 1000

# Time Constants (in seconds)
DEFAULT_FRAME_RATE = 10  # frames per second
DEFAULT_MODULE_C_CYCLE_TIME = 0.1  # 100ms
DEFAULT_WATCHDOG_INTERVAL = 0  # 0 means disabled
DEFAULT_BROWSER_WAIT_TIME = 1  # seconds between browser launch attempts
MAX_BROWSER_LAUNCH_ATTEMPTS = 10

# Network Constants
DEFAULT_PORT = 8000
PORT_RANGE_MAX = 10  # Number of ports to try when finding available port
LOCALHOST = '127.0.0.1'

# WebSocket Constants
WEBSOCKET_DELAY = 0.01  # Base delay for WebSocket processing

# Simulation Constants
DEFAULT_SCALE_TIMING = 1.0  # Normal speed