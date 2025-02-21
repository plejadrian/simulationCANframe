
import asyncio
import logging
import webbrowser
import time
import requests
from threading import Thread
from device_emulator import DeviceA, DeviceB
from module_c import ModuleC
from cloud_app import CloudApp

logger = logging.getLogger(__name__)

def open_browser(port):
    """Wait for server to start and open browser"""
    url = f'http://127.0.0.1:{port}'
    max_attempts = 10
    
    for attempt in range(max_attempts):
        try:
            # Try to connect to server
            response = requests.get(url)
            if response.status_code == 200:
                logger.info(f"Server is ready, opening browser at {url}")
                webbrowser.open(url)
                return
        except requests.ConnectionError:
            logger.debug(f"Server not ready (attempt {attempt + 1}/{max_attempts})")
            time.sleep(1)
    
    logger.warning("Failed to detect server startup, trying to open browser anyway")
    webbrowser.open(url)



def get_available_port(start_port=8000):
    """Find an available port starting from start_port"""
    import socket
    
    for port in range(start_port, start_port + 10):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('', port))
                s.close()
                logger.info(f"Found available port: {port}")
                return port
        except OSError:
            continue
    raise RuntimeError("No available ports found in range 8000-8009")

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
        device_a = DeviceA(frame_rate=10)
        device_b = DeviceB(frame_rate=10)
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