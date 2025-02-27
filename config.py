"""Global configuration for simulation timing and settings.

This module provides functions to get and set global configuration values
that affect the behavior of the simulation.
"""

import logging
from constants import DEFAULT_SCALE_TIMING

# Configure module logger
logger = logging.getLogger(__name__)

# Global scaling factor for timing (1.0 = normal speed, >1 = slower, <1 = faster)
SCALE_TIMING = DEFAULT_SCALE_TIMING

def set_scale_timing(value: float) -> None:
    """Update the global timing scale.
    
    Args:
        value (float): The new timing scale value. Values greater than 1.0 slow down
                      the simulation, values less than 1.0 speed it up.
    
    Raises:
        ValueError: If the provided value is not positive.
    """
    if value <= 0:
        raise ValueError("Timing scale must be a positive value")
        
    global SCALE_TIMING
    old_value = SCALE_TIMING
    SCALE_TIMING = float(value)
    logger.info(f"Timing scale changed from {old_value} to {SCALE_TIMING}")

def get_scale_timing() -> float:
    """Get the current timing scale.
    
    Returns:
        float: The current timing scale value.
    """
    return SCALE_TIMING