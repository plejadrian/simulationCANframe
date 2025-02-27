
import asyncio
import logging
import webbrowser
import time
import requests
import socket
from threading import Thread
from device_emulator import DeviceA, DeviceB
from module_c import ModuleC
from cloud_app import CloudApp
from constants import DEFAULT_PORT, PORT_RANGE_MAX, LOCALHOST, DEFAULT_FRAME_RATE, MAX_BROWSER_LAUNCH_ATTEMPTS, DEFAULT_BROWSER_WAIT_TIME

logger = logging.getLogger(__name__)

def open_browser(port: int) -> None:
    """Wait for server to start and open browser
    
    Args:
        port (int): The port number where the server is running
        
    Note:
        This function attempts to connect to the server multiple times before
        opening the browser to ensure the server is ready.
    """
    url = f'http://{LOCALHOST}:{port}'
    
    for attempt in range(MAX_BROWSER_LAUNCH_ATTEMPTS):
        try:
            # Try to connect to server
            response = requests.get(url)
            if response.status_code == 200:
                logger.info(f"Server is ready, opening browser at {url}")
                webbrowser.open(url)
                return
        except requests.ConnectionError:
            logger.debug(f"Server not ready (attempt {attempt + 1}/{MAX_BROWSER_LAUNCH_ATTEMPTS})")
            time.sleep(DEFAULT_BROWSER_WAIT_TIME)
        except Exception as e:
            logger.error(f"Error checking server status: {e}")
            time.sleep(DEFAULT_BROWSER_WAIT_TIME)
    
    logger.warning("Failed to detect server startup, trying to open browser anyway")
    webbrowser.open(url)



def get_available_port(start_port: int = DEFAULT_PORT) -> int:
    """Find an available port starting from start_port
    
    Args:
        start_port (int): The starting port number to check
        
    Returns:
        int: An available port number
        
    Raises:
        RuntimeError: If no available ports are found in the specified range
    """
    for port in range(start_port, start_port + PORT_RANGE_MAX):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('', port))
                s.close()
                logger.info(f"Found available port: {port}")
                return port
        except OSError:
            logger.debug(f"Port {port} is not available, trying next port")
            continue
    
    error_msg = f"No available ports found in range {start_port}-{start_port + PORT_RANGE_MAX - 1}"
    logger.error(error_msg)
    raise RuntimeError(error_msg)

def main():
    # Configure detailed logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('simulation.log')
        ]
    )

    try:
        # Initialize devices
        device_a = DeviceA(frame_rate=DEFAULT_FRAME_RATE)
        device_b = DeviceB(frame_rate=DEFAULT_FRAME_RATE)
        module_c = ModuleC()

        # Create CloudApp instance
        cloud_app = CloudApp(device_a, device_b, module_c)
        
        # Get available port
        port = get_available_port()
        
        # Launch browser in a separate thread
        browser_thread = Thread(target=open_browser, args=(port,), daemon=True)
        browser_thread.start()
        logger.info(f"Browser thread started for port {port}")
        
        # Run the FastAPI application
        cloud_app.run(port=port)
        
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Error running server: {e}")
        raise

if __name__ == "__main__":
    main()