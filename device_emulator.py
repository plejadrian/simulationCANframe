import asyncio
import logging
import time
from can_frame import CANFrame
from config import get_scale_timing

# Configure logging with debug level
logging.basicConfig(
    level=logging.DEBUG,  # Changed from INFO to DEBUG
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DeviceA:
    """Device A emulator - reports status but doesn't accept commands"""
    def __init__(self, frame_rate=10):
        self._base_frame_rate = frame_rate  # Store base frame rate
        self.status = {
            "operational": self._get_operational_value(),
            "frame_rate": frame_rate,
            "uptime": 0
        }
        self._start_time = time.time()
        self._running = True
        
    def set_running(self, state: bool):
        """Set device running state"""
        self._running = state
        logger.debug(f"Device A running state set to: {state}")
        
    @property
    def frame_rate(self):
        """Get the scaled frame rate"""
        return self._base_frame_rate / get_scale_timing()
        
    def _get_operational_value(self):
        """Get operational value based on current second:
        1: 00-20 seconds
        2: 21-40 seconds
        3: 41-00 seconds
        """
        current_second = int(time.time()) % 60
        if current_second <= 20:
            return 1
        elif current_second <= 40:
            return 2
        else:
            return 3
        
    async def generate_frames(self):
        """Generate status frames at configured rate"""
        logger.debug("Device A: Starting frame generation")
        while True:
            if self._running:  # Only generate frames when running
                # Update status values
                current_time = time.time()
                self.status["uptime"] = int(current_time - self._start_time)
                self.status["operational"] = self._get_operational_value()
                self.status["frame_rate"] = self.frame_rate
                
                # Create status frame
                frame = CANFrame(
                    extended=True,
                    remote=False,
                    can_id=0x18FF0001,
                    data=[
                        self.status["operational"],  # Operational value as first byte
                        (self.status["uptime"] >> 24) & 0xFF,  # Uptime as 4 bytes
                        (self.status["uptime"] >> 16) & 0xFF,
                        (self.status["uptime"] >> 8) & 0xFF,
                        self.status["uptime"] & 0xFF
                    ]
                )
                
                logger.debug(f"Device A generating frame with operational={self.status['operational']}")
                yield frame.to_ethernet()
            
            await asyncio.sleep(1.0 / self.frame_rate)

class DeviceB:
    """Device B emulator - reports status and accepts control commands"""
    def __init__(self, frame_rate=10):
        self._base_frame_rate = frame_rate  # Store base frame rate
        self.registers = {
            "control": 0,
            "status": 0,
            "watchdog": 0,
            "watchdog_status": "ok",
            "last_command": 0
        }
        self._last_watchdog_reset = time.time()
        self._base_watchdog_timeout = 0.5  # Base timeout (500ms)
        self._watchdog_task = None
        self._running = True
        self._frozen = False
        self._frozen_watchdog_status = None  # Store watchdog status when frozen
        
    def set_running(self, state: bool):
        """Set device running state"""
        self._running = state
        if not state:  # If stopping, also set frozen state
            self._frozen = True
            # Store current watchdog state when freezing
            self._frozen_watchdog_status = self.registers["watchdog_status"]
        else:  # If starting, clear frozen state
            self._frozen = False
            # Restore frozen watchdog state if it exists
            if self._frozen_watchdog_status is not None:
                self.registers["watchdog_status"] = self._frozen_watchdog_status
                self._frozen_watchdog_status = None
        logger.debug(f"Device B running state set to: {state}")
        
    @property
    def frame_rate(self):
        """Get the scaled frame rate"""
        return self._base_frame_rate / get_scale_timing()
        
    @property
    def _watchdog_timeout(self):
        """Get the scaled watchdog timeout"""
        return self._base_watchdog_timeout * get_scale_timing()
        
    async def start_watchdog(self):
        """Start the watchdog monitor if not already running"""
        if not self._watchdog_task or self._watchdog_task.done():
            self._watchdog_task = asyncio.create_task(self._watchdog_monitor())
        return self._watchdog_task

    async def _watchdog_monitor(self):
        """Monitor watchdog status"""
        logger.debug("Device B: Starting watchdog monitor")
        while True:
            try:
                # Only check watchdog when running and not frozen
                if self._running and not self._frozen:
                    current_time = time.time()
                    if current_time - self._last_watchdog_reset > self._watchdog_timeout:
                        if self.registers["watchdog_status"] != "triggered":
                            self.registers["watchdog_status"] = "triggered"
                            logger.warning("Watchdog triggered")
                await asyncio.sleep(0.1 * get_scale_timing())
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Watchdog monitor error: {e}")
                await asyncio.sleep(0.1)
            
    async def generate_frames(self):
        """Generate status frames at configured rate"""
        logger.debug("Device B: Starting frame generation")
        # Initialize watchdog monitor when frames start generating
        await self.start_watchdog()
            
        while True:
            if self._running:  # Only generate frames when running
                # Ensure control value is properly included
                frame = CANFrame(
                    extended=True,
                    remote=False,
                    can_id=0x18FF0002,  # Example status frame ID
                    data=[
                        self.registers["status"] & 0xFF,
                        self.registers["control"] & 0xFF,  # Control value as second byte
                        self.registers["watchdog"] & 0xFF,
                        0x01 if self.registers["watchdog_status"] == "ok" else 0x00
                    ]
                )
                
                logger.debug(f"Device B generating frame with control={self.registers['control']}")
                yield frame.to_ethernet()
            
            await asyncio.sleep(1.0 / self.frame_rate)
            
    async def handle_frame(self, data):
        """Handle incoming control frames"""
        try:
            # Don't process frames if frozen
            if self._frozen:
                return

            frame = CANFrame.from_ethernet(data)
            logger.debug(f"Device B received frame: CAN ID={frame.can_id:X}, Data={frame.data}")
            
            # Handle watchdog reset (CAN ID 0x100)
            if frame.can_id == 0x100:
                self._last_watchdog_reset = time.time()
                self.registers["watchdog"] = frame.data[0]
                self.registers["watchdog_status"] = "ok"
                logger.debug("Watchdog reset received")
            
            # Handle control command (CAN ID 0x200)
            elif frame.can_id == 0x200:
                control_value = frame.data[0]
                self.registers["control"] = control_value
                self.registers["last_command"] = time.time()
                logger.debug(f"Control value updated to: {control_value}")
            
        except Exception as e:
            logger.error(f"Error handling frame in Device B: {e}")
            raise
        
    def __del__(self):
        """Cleanup when object is destroyed"""
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()

class DeviceEmulator:
    def __init__(self, device_id: str):
        self.device_id = device_id
        self._running = True
        self._frozen = False
        self._cycle_time = 1.0

    def set_running(self, state: bool):
        """Set device running state"""
        self._running = state
        if not state:  # If stopping, also set frozen state
            self._frozen = True
        else:  # If starting, clear frozen state
            self._frozen = False
        logger.debug(f"Device {self.device_id} running state set to: {state}")

    async def run(self):
        """Main device loop"""
        while True:
            if self._running and not self._frozen:
                # Process only when running and not frozen
                await self._process_cycle()
            await asyncio.sleep(self._cycle_time)