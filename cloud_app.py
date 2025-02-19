import asyncio
import logging
import time
import socket
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
import uvicorn
from can_frame import CANFrame
from config import get_scale_timing, set_scale_timing

logger = logging.getLogger(__name__)

# FastAPI models
class ControlValue(BaseModel):
    control_value: int

class WatchdogInterval(BaseModel):
    interval: float

class ScaleTiming(BaseModel):
    scale: float

class CloudApp:
    """Central node for communication between devices and web interface"""
    def __init__(self, device_a, device_b, module_c):
        self.device_a = device_a
        self.device_b = device_b
        self.module_c = module_c
        self.watchdog_task = None
        self.watchdog_interval = 0
        self._last_received_frames = {}
        self._auto_watchdog_enabled = False
        self._last_watchdog_status = "ok"
        self._last_watchdog_reset_time = time.time()
        self._device_a_generator = None
        self._device_b_generator = None
        self._device_tasks = []
        self._running = False
        self._frozen = False
        self._reset_counters_task = None  # Add task reference
        
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
        self._frame_handlers = {
            0x18FF0001: self._handle_device_a_frame,  # Device A status
            0x18FF0002: self._handle_device_b_frame,  # Device B status
            0x100: self._handle_watchdog_frame,       # Watchdog
            0x200: self._handle_control_frame         # Control
        }
        
        # Initialize FastAPI
        self.app = FastAPI(lifespan=self._lifespan)
        self.setup_routes()
        self._active_websockets = set()
        
    @asynccontextmanager
    async def _lifespan(self, app: FastAPI):
        """Manage application lifecycle"""
        logger.info("Starting CloudApp and all devices")
        # Start counter reset task here where we have an event loop
        self._reset_counters_task = asyncio.create_task(self._reset_counters_periodic())
        await self.start()
        yield
        logger.info("Shutting down CloudApp and all devices")
        if self._reset_counters_task:
            self._reset_counters_task.cancel()
        await self.stop()

    def setup_routes(self):
        """Setup all FastAPI routes and WebSocket endpoint"""
        # Static files
        self.app.mount("/static", StaticFiles(directory="static"), name="static")
        
        # CORS middleware
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # REST endpoints
        @self.app.get("/")
        async def root():
            return RedirectResponse(url="/static/index.html")
            
        @self.app.get("/status")
        async def get_status():
            return self.get_status()
            
        @self.app.post("/device_b/control")
        async def control_device_b(value: ControlValue):
            return await self.send_control_value(value.control_value)
            
        @self.app.post("/watchdog/interval")
        async def set_watchdog_interval(value: WatchdogInterval):
            return self.set_watchdog_interval(value.interval)
            
        @self.app.post("/watchdog/reset")
        async def reset_watchdog():
            try:
                result = await self.send_watchdog_reset()
                logger.info("Manual watchdog reset endpoint called successfully")
                return result
            except Exception as e:
                logger.error(f"Error in watchdog reset endpoint: {e}")
                return {"status": "error", "message": str(e)}
                
        @self.app.get("/timing/scale")
        async def get_timing_scale():
            return {"scale": get_scale_timing()}
            
        @self.app.post("/timing/scale")
        async def set_timing_scale(value: ScaleTiming):
            set_scale_timing(value.scale)
            return {"status": "ok", "scale": get_scale_timing()}
            
        @self.app.post("/control/halt")
        async def halt_server():
            """Gracefully shut down the server"""
            logger.info("Halt command received, initiating shutdown...")
            # Give clients time to receive the response
            asyncio.create_task(self._delayed_shutdown())
            return {"status": "ok", "message": "Server halting..."}
            
        @self.app.post("/control/freeze")
        async def toggle_freeze():
            return await self.toggle_freeze()
            
        # WebSocket endpoint
        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await self._handle_websocket(websocket)

    async def _handle_websocket(self, websocket: WebSocket):
        """Handle WebSocket connection and messaging"""
        await websocket.accept()
        self._active_websockets.add(websocket)
        logger.debug("WebSocket connection accepted")
        
        try:
            # Start receiving messages
            while True:
                data = await websocket.receive_bytes()
                # Process through our pipeline with scaled timing
                await self.process_device_frame(data)
                # Add small delay scaled by simulation speed
                await asyncio.sleep(0.01 * get_scale_timing())
                logger.debug("WebSocket message processed through CloudApp")
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            self._active_websockets.remove(websocket)
            await websocket.close()
            logger.debug("WebSocket connection closed")

    async def _broadcast_frame(self, frame_bytes: bytes):
        """Broadcast frame to all connected WebSocket clients"""
        disconnected = set()
        for ws in self._active_websockets:
            try:
                await ws.send_bytes(frame_bytes)
            except Exception:
                disconnected.add(ws)
        
        # Clean up disconnected clients
        self._active_websockets.difference_update(disconnected)

    async def start(self):
        """Start all device tasks and frame broadcasting"""
        if not self._running:
            self._running = True
            # Initialize device generators
            self._device_a_generator = self.device_a.generate_frames()
            self._device_b_generator = self.device_b.generate_frames()
            
            # Initialize device B watchdog
            await self.device_b.start_watchdog()
            
            # Start ModuleC processing
            self._device_tasks.append(asyncio.create_task(self.module_c.process_data()))
            
            # Start frame broadcasting
            self._device_tasks.append(asyncio.create_task(self._frame_broadcaster()))
            
            # Start auto watchdog if enabled
            if self.watchdog_interval > 0:
                await self.start_auto_watchdog()
                
            logger.info("CloudApp started - all devices initialized")

    async def stop(self):
        """Stop all device tasks and cleanup"""
        self._running = False
        # Cancel all tasks
        for task in self._device_tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._device_tasks.clear()
        # Reset generators
        self._device_a_generator = None
        self._device_b_generator = None
        logger.info("CloudApp stopped - all devices cleaned up")
        
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
        logger.debug(f"CloudApp: Device A operational value {operational_value} sent to ModuleC")

    async def _handle_watchdog_frame(self, frame: CANFrame):
        """Handle watchdog reset frame"""
        self._pipeline_stats["watchdog_frames"] += 1
        self._last_watchdog_reset_time = time.time()
        logger.debug(f"CloudApp: Processing watchdog reset at {time.strftime('%H:%M:%S', time.localtime(self._last_watchdog_reset_time))}")

    async def _handle_device_b_frame(self, frame: CANFrame):
        """Handle Device B status frame"""
        self._pipeline_stats["device_b_frames"] += 1
        control_value = frame.data[1]  # Control value is in second byte
        self._last_watchdog_status = "ok" if frame.data[3] else "triggered"
        
        # Update Module C with the control value
        self.module_c.update_device_b(control_value)
        logger.debug(f"CloudApp: Device B control value {control_value} sent to ModuleC")
        logger.debug(f"CloudApp: Watchdog status is {self._last_watchdog_status}")

    async def _handle_control_frame(self, frame: CANFrame):
        """Handle control command frame"""
        self._pipeline_stats["control_frames"] += 1
        logger.debug(f"CloudApp: Processing control command with value {frame.data[0]}")

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

    async def start_auto_watchdog(self):
        """Start automatic watchdog reset if interval > 0"""
        if self.watchdog_task:
            self.watchdog_task.cancel()
            await asyncio.sleep(0)  # Allow task to be cancelled
            
        if self.watchdog_interval > 0:
            self._auto_watchdog_enabled = True
            self.watchdog_task = asyncio.create_task(self._watchdog_sender())
            logger.debug(f"Auto watchdog started with interval {self.watchdog_interval}s")
        else:
            self._auto_watchdog_enabled = False
        
    async def _watchdog_sender(self):
        """Send periodic watchdog reset frames"""
        try:
            while self._auto_watchdog_enabled:
                if not self._frozen:  # Only process watchdog when not frozen
                    frame = CANFrame(
                        extended=False,
                        remote=False,
                        can_id=0x100,
                        data=[0x01]
                    )
                    await self.device_b.handle_frame(frame.to_ethernet())
                    self._last_watchdog_reset_time = time.time()
                    logger.debug(f"Auto watchdog reset sent at {time.strftime('%H:%M:%S', time.localtime(self._last_watchdog_reset_time))}")
                await asyncio.sleep(self.watchdog_interval * get_scale_timing())
                
        except asyncio.CancelledError:
            logger.debug("Auto watchdog task cancelled")
            self._auto_watchdog_enabled = False
        except Exception as e:
            logger.error(f"Error in watchdog sender: {e}")
            self._auto_watchdog_enabled = False
            
    async def _watchdog_monitor(self):
        """Monitor watchdog state and auto-reset if enabled"""
        while True:
            if not self._frozen:  # Only process watchdog when not frozen
                if self.auto_watchdog_enabled:
                    current_time = time.time()
                    if current_time - self._last_watchdog_time >= self.auto_watchdog_interval:
                        await self._reset_watchdog()
                        self._last_watchdog_time = current_time
                        logger.debug(f"Auto watchdog reset sent at {time.strftime('%H:%M:%S')}")
            await asyncio.sleep(0.1)  # Short sleep to prevent CPU overuse

    async def _device_b_watchdog(self):
        """Monitor Device B watchdog status"""
        while True:
            if not self._frozen:  # Only check watchdog when not frozen
                current_time = time.time()
                if current_time - self._last_watchdog_time > self.WATCHDOG_TIMEOUT:
                    if not self._watchdog_triggered:
                        logger.warning("Watchdog triggered")
                        self._watchdog_triggered = True
                        self.device_b.watchdog_status = "triggered"
            await asyncio.sleep(0.1)

    def set_watchdog_interval(self, interval: float):
        """Set the interval for automatic watchdog reset"""
        self.watchdog_interval = max(0, float(interval))
        asyncio.create_task(self.start_auto_watchdog())
        return {
            "status": "ok",
            "interval": self.watchdog_interval,
            "auto_watchdog_enabled": self.watchdog_interval > 0
        }
    
    async def send_control_value(self, value: int):
        """Send control value to Device B through CAN frame"""
        try:
            # Validate value range
            if not 0 <= value <= 255:
                raise ValueError("Control value must be between 0 and 255")
            
            logger.info(f"Control value {value} initiated through CloudApp")
            frame = CANFrame(
                extended=False,
                remote=False,
                can_id=0x200,  # Control command ID
                data=[value & 0xFF]  # Ensure single byte
            )
            frame_bytes = frame.to_ethernet()
            
            # Process through our standard pipeline first
            logger.debug(f"Processing control value frame through CloudApp pipeline")
            await self.process_device_frame(frame_bytes)
            
            # Then send to Device B
            logger.debug(f"Sending control value frame to Device B")
            await self.device_b.handle_frame(frame_bytes)
            
            timestamp = time.strftime("%H:%M:%S", time.localtime(time.time()))
            logger.info(f"Control value {value} set through CloudApp at {timestamp}")
            
            # Update Device B registers immediately
            self.device_b.registers["control"] = value
            self.device_b.registers["last_command"] = time.time()
            
            return {
                "status": "ok",
                "value": value,
                "timestamp": timestamp,
                "message": f"Control value {value} processed through CloudApp pipeline"
            }
        except Exception as e:
            logger.error(f"Error setting control value: {e}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    async def send_watchdog_reset(self):
        """Send manual watchdog reset to Device B"""
        try:
            logger.info("Manual watchdog reset initiated through CloudApp")
            frame = CANFrame(
                extended=False,
                remote=False,
                can_id=0x100,  # Watchdog reset ID
                data=[0x01]
            )
            frame_bytes = frame.to_ethernet()
            
            # Process the frame through our standard pipeline
            logger.debug("Processing watchdog reset frame through CloudApp pipeline")
            await self.process_device_frame(frame_bytes)
            
            # Then send it to Device B
            logger.debug("Sending watchdog reset frame to Device B")
            await self.device_b.handle_frame(frame_bytes)
            
            self._last_watchdog_reset_time = time.time()
            timestamp = time.strftime("%H:%M:%S", time.localtime(self._last_watchdog_reset_time))
            logger.info(f"Manual watchdog reset completed at {timestamp}")
            
            return {
                "status": "ok",
                "timestamp": timestamp,
                "message": "Watchdog reset processed through central CloudApp",
                "watchdog_status": self._last_watchdog_status
            }
        except Exception as e:
            logger.error(f"Error in manual watchdog reset: {e}")
            raise
    
    def get_status(self):
        """Get current status of all components"""
        # Format timestamps in device_b registers if they exist
        device_b_status = self.device_b.registers.copy()
        if device_b_status["last_command"] > 0:
            device_b_status["last_command"] = time.strftime("%H:%M:%S", time.localtime(device_b_status["last_command"]))

        # If frozen, ensure we return the frozen watchdog status
        if self._frozen and hasattr(self.device_b, '_frozen_watchdog_status'):
            device_b_status["watchdog_status"] = self.device_b._frozen_watchdog_status

        return {
            "device_a": self.device_a.status,
            "device_b": device_b_status,
            "module_c": {
                **self.module_c.last_values,
                "is_frozen": self.module_c.is_frozen 
            },                    
            "cloud_app": {
                "auto_watchdog_interval": self.watchdog_interval,
                "auto_watchdog_enabled": self._auto_watchdog_enabled,
                "last_watchdog_status": self._last_watchdog_status,
                "last_watchdog_reset": time.strftime("%H:%M:%S", time.localtime(self._last_watchdog_reset_time)),
                "last_received_frame_ids": [f"0x{id:X}" for id in self._last_received_frames.keys()],
                "pipeline_stats": {
                    **self._pipeline_stats,
                    "last_frame_time": time.strftime("%H:%M:%S", 
                        time.localtime(self._pipeline_stats["last_frame_time"]))
                        if self._pipeline_stats["last_frame_time"] > 0 else "Never"
                },
                "frozen": self._frozen  # Add frozen state to status response
            }
        }

    async def get_device_a_frame(self):
        """Get next frame from Device A through CloudApp pipeline"""
        if not self._running:
            await self.start()
        if not self._device_a_generator:
            self._device_a_generator = self.device_a.generate_frames()
        try:
            frame_bytes = await anext(self._device_a_generator)
            # Process through our pipeline
            await self.process_device_frame(frame_bytes)
            return frame_bytes
        except (StopAsyncIteration, StopIteration):
            self._device_a_generator = self.device_a.generate_frames()
            return None
        except Exception as e:
            logger.error(f"Error getting Device A frame: {e}")
            return None

    async def get_device_b_frame(self):
        """Get next frame from Device B through CloudApp pipeline"""
        if not self._running:
            await self.start()
        if not self._device_b_generator:
            self._device_b_generator = self.device_b.generate_frames()
        try:
            frame_bytes = await anext(self._device_b_generator)
            # Process through our pipeline
            await self.process_device_frame(frame_bytes)
            return frame_bytes
        except (StopAsyncIteration, StopIteration):
            self._device_b_generator = self.device_b.generate_frames()
            return None
        except Exception as e:
            logger.error(f"Error getting Device B frame: {e}")
            return None

    async def _frame_broadcaster(self):
        """Continuously broadcast device frames to all WebSocket clients"""
        try:
            while True:  # Changed from self._running to True to keep task alive
                if self._running and not self._frozen:  # Only process frames when not frozen
                    # Get and broadcast Device A frame
                    frame = await self.get_device_a_frame()
                    if frame:
                        await self._broadcast_frame(frame)
                    
                    # Get and broadcast Device B frame
                    frame = await self.get_device_b_frame()
                    if frame:
                        await self._broadcast_frame(frame)
                
                # Base rate 10Hz scaled by simulation speed
                await asyncio.sleep(0.1 * get_scale_timing())
        except Exception as e:
            logger.error(f"Frame broadcaster error: {e}")

    async def _delayed_shutdown(self):
        """Perform delayed shutdown to allow response to be sent"""
        await asyncio.sleep(1)
        logger.info("Executing server shutdown...")
        # Send SIGTERM to our own process
        import os
        import signal
        os.kill(os.getpid(), signal.SIGTERM)

    async def toggle_freeze(self):
        """Toggle freeze state for all components"""
        self._frozen = not self._frozen  # Toggle freeze state
        self.set_frozen(self._frozen)
        state = "frozen" if not self._running else "running"
        logger.info(f"Server state changed to: {state}")
        
        return {
            "status": "ok",
            "state": state,
            "message": f"Server is now {state}"
        }

    def set_frozen(self, state: bool):
        """Set the frozen state of the application"""
        self._frozen = state
        logger.info(f"Application freeze state set to: {state}")
        if state:
            # Pause device emulators and monitoring when frozen
            self.device_a.set_running(False)
            self.device_b.set_running(False)
            self.module_c.set_running(False)
            # Save current watchdog state and disable it temporarily
            self._watchdog_state_before_freeze = self._auto_watchdog_enabled
            self._auto_watchdog_enabled = False
            if self.watchdog_task and not self.watchdog_task.done():
                self.watchdog_task.cancel()
        else:
            # Resume device emulators and monitoring when unfrozen
            self.device_a.set_running(True)
            self.device_b.set_running(True)
            self.module_c.set_running(True)
            # Restore previous watchdog state
            if hasattr(self, '_watchdog_state_before_freeze'):
                self._auto_watchdog_enabled = self._watchdog_state_before_freeze
                if self._auto_watchdog_enabled:
                    asyncio.create_task(self.start_auto_watchdog())

    async def _reset_counters_periodic(self):
        """Periodically reset frame counters to ensure accurate rates"""
        while True:
            await asyncio.sleep(10)  # Reset every 10 seconds
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

    def run( self, host="0.0.0.0", port=None ):
        """Run the FastAPI application with automatic port selection"""

        if port is not None:
            logger.info( f"CloudApp server, port is already assignet to:{port}" )
        else:
            # Find available port
            for p in range(8000, 8010):
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.bind((host, p))
                    sock.close()
                    port = p
                    break
                except socket.error:
                    continue
            
            if port is None:
                raise RuntimeError("No available ports found in range 8000-8009!")
        
        logger.info(f"Starting CloudApp server on http://{host}:{port}")

        # Use FastAPI's shutdown event instead of callback manager
        @self.app.on_event("shutdown")
        async def shutdown_handler():
            logger.info("Shutting down server...")
            await self.stop()
            # Give tasks time to clean up
            await asyncio.sleep(1)
            for task in asyncio.all_tasks():
                if task is not asyncio.current_task():
                    task.cancel()

        try:
            config = uvicorn.Config(
                self.app,
                host=host,
                port=port,
                reload=False,
                log_level="debug",
                access_log=True,
                workers=1,
                log_config=None  # Use our custom logging configuration
            )
            server = uvicorn.Server(config)
            server.run()
        except Exception as e:
            logger.error(f"Failed to start server: {e}")
            raise


