from constants import CAN_STANDARD_ID_MAX, CAN_EXTENDED_ID_MAX, CAN_FRAME_MAX_DATA_LENGTH

class CANFrame:
    def __init__(self, extended=False, remote=False, can_id=0, data=None):
        """
        Initialize a CAN frame
        
        Args:
            extended (bool): True for extended frame (29-bit ID), False for standard frame (11-bit ID)
            remote (bool): True for remote frame, False for data frame
            can_id (int): CAN identifier (11 or 29 bits)
            data (list): Data bytes (up to 8 bytes)
            
        Raises:
            ValueError: If CAN ID exceeds allowed range or data length exceeds 8 bytes
            TypeError: If data is not iterable
        """
        self.extended = extended
        self.remote = remote
        self.can_id = can_id
        self.data = data if data is not None else []
        
        # Validate CAN ID length
        max_id = CAN_EXTENDED_ID_MAX if extended else CAN_STANDARD_ID_MAX
        if not 0 <= can_id <= max_id:
            raise ValueError(f"Invalid CAN ID for {'extended' if extended else 'standard'} frame")
        
        # Validate data length
        if len(self.data) > CAN_FRAME_MAX_DATA_LENGTH:
            raise ValueError(f"Data length cannot exceed {CAN_FRAME_MAX_DATA_LENGTH} bytes")
            
        # Validate data type
        try:
            self.data = list(self.data)
        except TypeError:
            raise TypeError("Data must be an iterable type")
        
    def to_ethernet(self):
        """Convert CAN frame to Ethernet format"""
        # Create control byte: [FF|RTR|rsvd|rsvd|B3|B2|B1|B0]
        control = (
            (0x80 if self.extended else 0x00) |  # FF bit
            (0x40 if self.remote else 0x00) |    # RTR bit
            (len(self.data) & 0x0F)              # Data length (B3~B0)
        )
        
        # Format CAN ID
        if self.extended:
            id_bytes = [
                (self.can_id >> 24) & 0xFF,
                (self.can_id >> 16) & 0xFF,
                (self.can_id >> 8) & 0xFF,
                self.can_id & 0xFF
            ]
        else:
            id_bytes = [
                0x00,
                0x00,
                (self.can_id >> 8) & 0xFF,
                self.can_id & 0xFF
            ]
            
        # Format data with padding
        data_bytes = list(self.data) + [0] * (8 - len(self.data))
        
        return bytes([control] + id_bytes + data_bytes)
    
    @classmethod
    def from_ethernet(cls, data):
        """Create CAN frame from Ethernet data"""
        if len(data) != 13:
            raise ValueError("Invalid frame length")
            
        control = data[0]
        extended = bool(control & 0x80)
        remote = bool(control & 0x40)
        length = control & 0x0F
        
        if extended:
            can_id = int.from_bytes(data[1:5], 'big')
        else:
            can_id = int.from_bytes(data[3:5], 'big')
            
        frame_data = list(data[5:5+length])
        
        return cls(extended, remote, can_id, frame_data)
