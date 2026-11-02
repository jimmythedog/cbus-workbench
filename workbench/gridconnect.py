"""GridConnect frame checks and extraction shared by TCP and serial connections."""


def validate_frame(frame: bytes) -> None:
    """Require one complete, printable ASCII frame before sending."""
    if (
        len(frame) < 3
        or not frame.startswith(b":")
        or not frame.endswith(b";")
        or frame.count(b":") != 1
        or frame.count(b";") != 1
        or not all(32 <= byte <= 126 for byte in frame)
    ):
        raise ValueError("Expected one complete printable ASCII GridConnect frame")


def extract_frames(buffer: bytearray) -> list[bytes]:
    """Remove complete delimited frames, leaving any unfinished frame in buffer.

    Incoming bytes are only delimited here, not validated as outgoing frames are.
    """
    frames = []
    while True:
        start = buffer.find(b":")
        if start < 0:
            buffer.clear()
            return frames
        if start:
            del buffer[:start]

        end = buffer.find(b";")
        if end < 0:
            return frames

        frames.append(bytes(buffer[: end + 1]))
        del buffer[: end + 1]
