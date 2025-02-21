"""Global configuration for simulation timing"""

# Global scaling factor for timing (1.0 = normal speed, >1 = slower, <1 = faster)
SCALE_TIMING = 1.0

def set_scale_timing(value: float):
    """Update the global timing scale"""
    global SCALE_TIMING
    SCALE_TIMING = float(value)

def get_scale_timing():
    """Get the current timing scale"""
    return SCALE_TIMING