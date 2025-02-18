import asyncio
import logging
from device_emulator import DeviceA, DeviceB
from module_c import ModuleC
from cloud_app import CloudApp

logger = logging.getLogger(__name__)

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

    logger = logging.getLogger(__name__)
    
    try:
        # Initialize devices
        device_a = DeviceA(frame_rate=10)
        device_b = DeviceB(frame_rate=10)
        module_c = ModuleC()

        # Create CloudApp instance
        cloud_app = CloudApp(device_a, device_b, module_c)
        
        # Run the FastAPI application
        cloud_app.run()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Error running server: {e}")
        raise

if __name__ == "__main__":
    main()
