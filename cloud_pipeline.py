import asyncio
import logging
import time
from typing import Dict, Any, Callable, Awaitable
from can_frame import CANFrame
from config import get_scale_timing
from constants import (
    DEVICE_A_STATUS_ID,
    DEVICE_B_STATUS_ID,
    WATCHDOG_FRAME_ID,
    CONTROL_FRAME_ID
)

logger = logging.getLogger(__name__)

class CloudPipeline:
    """Handles the cloud pipeline functionality for processing CAN frames"""
    
    def __init__(self, device_a, device_b, module_c):
        self.device_a = device_a
        self.device_b = device_b
        self.module_c = module_c
        self._last_received_frames = {}
        self._last_watchdog_status = "ok"
        self._last_watchdog_reset_time = time.time()
        self._frozen = False
        
        # Initialize statistics for pipeline monitoring
        self._pipeline_stats = {
            "frames_processed": 0,
            "device_a_frames": 0,
            "device_b_frames": 0,
            "control_frames": 0,
            "watchdog_frames": 0,
            "last_frame_time": 0,
            "frame_rates": {
                "device_a": 0.0,
                "device_b": 0.0,
                "total": 0.0
            },
            "last_rates_update": time.time()
        }
        
        # Add frame handlers mapping
        self._frame_handlers: Dict[int, Callable[[CANFrame], Awaitable[None]]] = {
            DEVICE_A_STATUS_ID: self._handle_device_a_frame,  # Device A status
            DEVICE_B_STATUS_ID: self._handle_device_b_frame,  # Device B status
            WATCHDOG_FRAME_ID: self._handle_watchdog_frame,   # Watchdog
            CONTROL_FRAME_ID: self._handle_control_frame      # Control
        }
        
        # Start the counter reset task
        self._reset_counters_task = None
    
    async def start(self):
        """Start the pipeline processing"""
        # Start counter reset task
        self._reset_counters_task = asyncio.create_task(self._reset_counters_periodic())
    
    async def stop(self):
        """Stop the pipeline processing"""
        if self._reset_counters_task and not self._reset_counters_task.done():
            self._reset_counters_task.cancel()
            try:
                await self._reset_counters_task
            except asyncio.CancelledError:
                pass
    
    def set_frozen(self, state: bool):
        """Set the frozen state of the pipeline"""
        self._frozen = state
    
    async def process_device_frame(self, frame_bytes: bytes):
        """Process incoming frame through the pipeline"""
        try:
            frame = CANFrame.from_ethernet(frame_bytes)
            current_time = time.time()
            
            # Don't process if frozen
            if self._frozen:
                return frame

            # Always increment the processed frames counter
            self._pipeline_stats["frames_processed"] += 1
            self._pipeline_stats["last_frame_time"] = current_time
            
            # Call appropriate frame handler based on CAN ID
            if frame.can_id in self._frame_handlers:
                await self._frame_handlers[frame.can_id](frame)
                
            # Store frame for reference
            self._last_received_frames[frame.can_id] = frame
            
            return frame
            
        except Exception as e:
            logger.error(f"Error processing frame: {e}")
            raise
    
    async def _handle_device_a_frame(self, frame: CANFrame):
        """Handle Device A status frame"""
        self._pipeline_stats["device_a_frames"] += 1
        # Update ModuleC with Device A's operational value from first byte
        operational_value = frame.data[0]
        self.module_c.update_device_a(operational_value)
        # Update Device A's status with latest values
        self.device_a.status["operational"] = operational_value
        uptime_bytes = frame.data[1:5]
        self.device_a.status["uptime"] = int.from_bytes(uptime_bytes, 'big')
        logger.debug(f"CloudPipeline: Device A operational value {operational_value} sent to ModuleC")

    async def _handle_watchdog_frame(self, frame: CANFrame):
        """Handle watchdog reset frame"""
        self._pipeline_stats["watchdog_frames"] += 1
        self._last_watchdog_reset_time = time.time()
        logger.debug(f"CloudPipeline: Processing watchdog reset at {time.strftime('%H:%M:%S', time.localtime(self._last_watchdog_reset_time))}")

    async def _handle_device_b_frame(self, frame: CANFrame):
        """Handle Device B status frame"""
        self._pipeline_stats["device_b_frames"] += 1
        control_value = frame.data[1]  # Control value is in second byte
        self._last_watchdog_status = "ok" if frame.data[3] else "triggered"
        
        # Update Module C with the control value
        self.module_c.update_device_b(control_value)
        logger.debug(f"CloudPipeline: Device B control value {control_value} sent to ModuleC")
        logger.debug(f"CloudPipeline: Watchdog status is {self._last_watchdog_status}")

    async def _handle_control_frame(self, frame: CANFrame):
        """Handle control command frame"""
        self._pipeline_stats["control_frames"] += 1
        logger.debug(f"CloudPipeline: Processing control command with value {frame.data[0]}")
    
    async def _reset_counters_periodic(self):
        """Periodically reset frame counters to ensure accurate rates"""
        while True:
            await asyncio.sleep(10 * get_scale_timing())  # Now scaled by timing factor
            if not self._frozen:
                current_time = time.time()
                elapsed = current_time - self._pipeline_stats["last_rates_update"]
                
                # Calculate final rates before reset
                self._pipeline_stats["frame_rates"] = {
                    "device_a": (self._pipeline_stats["device_a_frames"] / max(1, elapsed)) * get_scale_timing(),
                    "device_b": (self._pipeline_stats["device_b_frames"] / max(1, elapsed)) * get_scale_timing(),
                    "total": (self._pipeline_stats["frames_processed"] / max(1, elapsed)) * get_scale_timing()
                }
                
                # Reset counters but keep the rates
                self._pipeline_stats.update({
                    "frames_processed": 0,
                    "device_a_frames": 0,
                    "device_b_frames": 0,
                    "control_frames": 0,
                    "watchdog_frames": 0,
                    "last_rates_update": current_time
                })
    
    def get_pipeline_status(self):
        """Get the current status of the pipeline"""
        return {
            "last_watchdog_status": self._last_watchdog_status,
            "last_watchdog_reset": time.strftime("%H:%M:%S", time.localtime(self._last_watchdog_reset_time)),
            "last_received_frame_ids": [f"0x{id:X}" for id in self._last_received_frames.keys()],
            "pipeline_stats": {
                **self._pipeline_stats,
                "last_frame_time": time.strftime("%H:%M:%S", 
                    time.localtime(self._pipeline_stats["last_frame_time"]))
                    if self._pipeline_stats["last_frame_time"] > 0 else "Never"
            },
            "frozen": self._frozen
        }