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

class DeviceEmulator:
    """Base class for device emulators"""
    def __init__(self, frame_rate=10):
        self._base_frame_rate = frame_rate
        self._running = True
        self._frozen = False
        self._start_time = time.time()
        self._frames_iterator = self.generate_frames()

    @property
    def frames_iterator(self):
        return self._frames_iterator

    def set_running(self, state: bool):
        """Set device running state"""
        self._running = state
        if not state:
            self._frozen = True
        else:
            self._frozen = False
        logger.debug(f"{self.__class__.__name__} running state set to: {state}")

    @property
    def frame_rate(self):
        """Get the scaled frame rate"""
        return self._base_frame_rate / get_scale_timing()

    async def generate_frames(self):
        """Generate status frames at configured rate - to be implemented by subclasses"""
        raise NotImplementedError


class DeviceA(DeviceEmulator):
    """Device A emulator - reports status but doesn't accept commands"""
    def __init__(self, frame_rate=10):
        super().__init__(frame_rate)
        self.status = {
            "operational": self._get_operational_value(),
            "frame_rate": frame_rate,
            "uptime": 0
        }

    def _get_operational_value(self):
        """Get operational value based on current second"""
        current_second = int(time.time()) % 60
        if current_second <= 20:
            return 1
        elif current_second <= 40:
            return 2
        return 3

    async def generate_frames(self):
        """Generate status frames at configured rate"""
        logger.debug("Device A: Starting frame generation")
        while True:
            if self._running:
                current_time = time.time()
                self.status.update({
                    "uptime": int(current_time - self._start_time),
                    "operational": self._get_operational_value(),
                    "frame_rate": self.frame_rate
                })

                frame = CANFrame(
                    extended=True,
                    remote=False,
                    can_id=0x18FF0001,
                    data=[
                        self.status["operational"],
                        (self.status["uptime"] >> 24) & 0xFF,
                        (self.status["uptime"] >> 16) & 0xFF,
                        (self.status["uptime"] >> 8) & 0xFF,
                        self.status["uptime"] & 0xFF
                    ]
                )
                
                logger.debug(f"Device A generating frame with operational={self.status['operational']}")
                yield frame.to_ethernet()
            
            await asyncio.sleep(1.0 / self.frame_rate)


class DeviceB(DeviceEmulator):
    """Device B emulator - reports status and accepts control commands"""
    def __init__(self, frame_rate=10):
        super().__init__(frame_rate)
        self.registers = {
            "control": 0,
            "status": 0,
            "watchdog": 0,
            "watchdog_status": "ok",
            "last_command": 0
        }
        self._last_watchdog_reset = time.time()
        self._base_watchdog_timeout = 0.5
        self._watchdog_task = None
        self._frozen_watchdog_status = None

        ###self.start_watchdog()        

    def set_running(self, state: bool):
        """Override to handle watchdog status"""
        super().set_running(state)
        if not state:
            self._frozen_watchdog_status = self.registers["watchdog_status"]
        else:
            if self._frozen_watchdog_status is not None:
                self.registers["watchdog_status"] = self._frozen_watchdog_status
                self._frozen_watchdog_status = None

    @property
    def _watchdog_timeout(self):
        """Get the scaled watchdog timeout"""
        return self._base_watchdog_timeout * get_scale_timing()
        
    def start_watchdog(self):
        """Start the watchdog monitor if not already running"""
        if not self._watchdog_task or self._watchdog_task.done():
            logger.debug("Device B: starting watchdog monitor task ")
            self._watchdog_task = asyncio.create_task(self._watchdog_monitor())


    async def _watchdog_monitor(self):
        """Monitor watchdog status"""
        logger.debug("Device B: watchdog monitor task created")
        while True:
            try:
                # Only check watchdog when running and not frozen
                if self._running and not self._frozen:
                    current_time = time.time()
                    if current_time - self._last_watchdog_reset > ( self._watchdog_timeout  + 0.03 ):
                    
                        if self.registers["watchdog_status"] != "triggered":
                            self.registers["watchdog_status"] = "triggered"
                            logger.warning("Watchdog triggered")
                await asyncio.sleep(0.1 * get_scale_timing())
            except asyncio.CancelledError:
                logger.debug("Watchdog monitor cancelled")
                break
            except Exception as e:
                logger.error(f"Watchdog monitor error: {e}")
                await asyncio.sleep(0.1)

    async def generate_frames(self):
        """Generate status frames at configured rate"""
        logger.debug("Device B: Starting frame generation")
        
        # # Initialize watchdog monitor when frames start generating
        # await self.start_watchdog()

        # Start watchdog monitor when frame generation begins
        if not self._watchdog_task or self._watchdog_task.done():
            self._watchdog_task = asyncio.create_task(self._watchdog_monitor())
            logger.debug("Device B: Watchdog monitor started before frame generation")


        while True:
            if self._running:
                frame = CANFrame(
                    extended=True,
                    remote=False,
                    can_id=0x18FF0002,
                    data=[
                        self.registers["status"],
                        self.registers["control"],
                        self.registers["watchdog"],
                        1 if self.registers["watchdog_status"] == "ok" else 0
                    ]
                )
                logger.debug(f"Device B generating frame with control={self.registers['control']}")
                yield frame.to_ethernet()
            
            await asyncio.sleep(1.0 / self.frame_rate)

    async def handle_frame(self, frame_bytes: bytes):
        """Handle incoming CAN frame"""
        try:
            # Don't process frames if frozen
            ###if self._frozen:
            ### return
            
            frame = CANFrame.from_ethernet(frame_bytes)
            logger.debug(f"Device B received frame: CAN ID={frame.can_id:X}, Data={frame.data}")
            
            if frame.can_id == 0x100:  # Watchdog reset
                self._last_watchdog_reset = time.time()
                self.registers["watchdog"] = 1
                self.registers["watchdog_status"] = "ok"
                logger.debug("Device B: Watchdog reset received")
                
            elif frame.can_id == 0x200:  # Control command
                self.registers["control"] = frame.data[0]
                self.registers["last_command"] = time.time()
                logger.debug(f"Device B: Control value set to {frame.data[0]}")
                
        except Exception as e:
            logger.error(f"Device B: Error handling frame: {e}")
            raise
        
    def __del__(self):
        """Cleanup when object is destroyed"""
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()

