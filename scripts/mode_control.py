from enum import IntEnum


class Mode(IntEnum):
    """Robot operating modes, ordered by index for tab switching."""
    USER       = 0
    AUTONOMOUS = 1
    LINE       = 2
    FACE       = 3   # Gender / age detection via DeepFace