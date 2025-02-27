import asyncio
import logging
from typing import Set, Callable, Awaitable
from fastapi import WebSocket, WebSocketDisconnect
from config import get_scale_timing
from constants import WEBSOCKET_DELAY

logger = logging.getLogger(__name__)

class WebSocketHandler:
    """Handles WebSocket connections and broadcasting for the simulation"""
    def __init__(self):
        self._active_websockets: Set[WebSocket] = set()
        
    async def handle_websocket(self, websocket: WebSocket, process_frame_callback: Callable[[bytes], Awaitable[None]]):
        """Handle WebSocket connection and messaging
        
        Args:
            websocket (WebSocket): The WebSocket connection to handle
            process_frame_callback (Callable): Callback function to process received frames
            
        Note:
            This method handles the entire WebSocket lifecycle including connection,
            message processing, and disconnection.
        """
        client_info = f"{websocket.client.host}:{websocket.client.port}"
        
        try:
            await websocket.accept()
            self._active_websockets.add(websocket)
            logger.info(f"WebSocket connection accepted from {client_info}")
            
            # Start receiving messages
            while True:
                try:
                    data = await websocket.receive_bytes()
                    # Process through our pipeline with scaled timing
                    await process_frame_callback(data)
                    # Add small delay scaled by simulation speed
                    await asyncio.sleep(WEBSOCKET_DELAY * get_scale_timing())
                    logger.debug(f"WebSocket message from {client_info} processed")
                except WebSocketDisconnect:
                    logger.info(f"WebSocket client {client_info} disconnected")
                    break
                except ValueError as e:
                    logger.warning(f"Invalid data received from {client_info}: {e}")
                except Exception as e:
                    logger.error(f"Error processing WebSocket message from {client_info}: {e}")
                    # Continue processing other messages despite errors
        except Exception as e:
            logger.error(f"WebSocket connection error with {client_info}: {e}")
        finally:
            if websocket in self._active_websockets:
                self._active_websockets.remove(websocket)
            try:
                await websocket.close()
            except Exception as e:
                logger.warning(f"Error closing WebSocket for {client_info}: {e}")
            logger.info(f"WebSocket connection closed for {client_info}")

    async def broadcast_frame(self, frame_bytes: bytes) -> int:
        """Broadcast frame to all connected WebSocket clients
        
        Args:
            frame_bytes (bytes): The frame data to broadcast
            
        Returns:
            int: Number of clients the frame was successfully sent to
        """
        disconnected = set()
        success_count = 0
        
        for ws in self._active_websockets:
            try:
                await ws.send_bytes(frame_bytes)
                success_count += 1
            except Exception as e:
                client_info = f"{ws.client.host}:{ws.client.port}" if hasattr(ws, 'client') else "unknown"
                logger.warning(f"Failed to send to client {client_info}: {e}")
                disconnected.add(ws)
        
        # Clean up disconnected clients
        if disconnected:
            logger.info(f"Removing {len(disconnected)} disconnected WebSocket clients")
            self._active_websockets.difference_update(disconnected)
            
        return success_count
        
    @property
    def active_connections_count(self):
        """Get the number of active WebSocket connections"""
        return len(self._active_websockets)