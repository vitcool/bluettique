from enum import Enum


class SystemState(Enum):
    INITIAL_CHECK = 0
    IDLE = 1
    LONG_IDLE = 2
    CHECK_STATUS = 3
    START_CHARGING = 4
    STOP_CHARGING = 5
    TURN_AC_ON = 6
    TURN_OFF = 7
    TURN_DC_OFF = 8
