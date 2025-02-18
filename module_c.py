import time
import asyncio
import logging
from config import get_scale_timing

logger = logging.getLogger(__name__)

class ModuleC:
    """Module C - performs real-time calculations on received data"""
    def __init__(self):
        self.last_values = {
            "device_a": 0,  # Numeric operational value from Device A (1, 2, or 3)
            "device_b": 0,  # Store single numeric value
            "calculation_result": 0,
            "last_calculation_time": 0
        }
        self._base_cycle_time = 0.1  # Base cycle time (100ms)
        self._running = True
        self._frozen = False
        
    def set_running(self, state: bool):
        """Set module running state"""
        self._running = state
        if not state:  # If stopping, also set frozen state
            self._frozen = True
        else:  # If starting, clear frozen state
            self._frozen = False
        logger.debug(f"Module C running state set to: {state}")
            
    @property
    def is_frozen(self) -> bool:
        """Get the current frozen state"""
        return self._frozen        

    @property
    def _cycle_time(self):
        """Get the scaled cycle time"""
        return get_scale_timing() * self._base_cycle_time
    
    def _get_operational_value(self):
        """Get operational value to multiply based on current second:
        1:    01-15 seconds
        10:   16-30 seconds
        100:  31-45 seconds
        1000: 46-00 seconds
        """
        current_second = int(time.time()) % 60
        if current_second <= 15:
            return 1
        elif current_second <= 30:
            return 10
        elif current_second <= 45:
            return 100
        else:
            return 1000
        
    async def process_data(self):
        """Process data in real-time with scaled cycle time"""
        while True:
            if self._running and not self._frozen:  # Only process when running and not frozen
                cycle_start = time.time()
                
                try:
                    # Calculate result based on device values and time of day
                    current_time = time.time()
                    ###time_weight = (current_time % 86400) / 86400  # 0.0 to 1.0 based on time of day
                    
                    # Weighted average calculation
                    self.last_values["calculation_result"] = (
                        (self.last_values["device_a"] +  
                        self.last_values["device_b"]) * 
                        self._get_operational_value()
                    )
                    self.last_values["last_calculation_time"] = current_time
                    logger.debug(f"Module C calculation: {self.last_values['calculation_result']:.3f} (device_a={self.last_values['device_a']}, device_b={self.last_values['device_b']})")
                        
                except Exception as e:
                    logger.error(f"Error in Module C processing: {e}")
                
                # Calculate sleep time to maintain precise cycle time
                cycle_end = time.time()
                processing_time = cycle_end - cycle_start
                sleep_time = max(0, self._cycle_time - processing_time)
                
                await asyncio.sleep(sleep_time)
            else:
                await asyncio.sleep(self._cycle_time)
        
    def update_device_a(self, value: int):
        """Update value received from Device A"""
        if not self._frozen:  # Only update if not frozen
            self.last_values["device_a"] = value
            logger.debug(f"Module C received Device A value: {value}")
        
    def update_device_b(self, value: int):
        """Update value received from Device B"""
        if not self._frozen:  # Only update if not frozen
            self.last_values["device_b"] = value
            logger.debug(f"Module C received Device B value: {value}")
