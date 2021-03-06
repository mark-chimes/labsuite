class ProtocolException(Exception):
    """
    A user-level Exception thrown when a Protocol is improperly defined.

    These are designed to provide information to the user on how to
    resolve specific issues in the definition or operation of a
    Protocol.
    """


# Can't be a ProtocolException or it'll be ignored when we want to do a
# PartialProtocol.
class PartialProtocolException(Exception):
    """
    Thrown when an invalid PartialProtocol is called in a way which
    would cause it to have side effects (such as running on a machine).
    """


class DataMissing(ProtocolException):
    """
    Thrown when not enough data is provided either by the user or the
    context to complete a call.
    """


class CalibrationMissing(ProtocolException):
    """
    Thrown when Calibration data is missing.
    """


class ProtocolConflict(ProtocolException):
    """
    Raised when a Protocol definition conflicts with another in the same
    Protocol, such as reuse of a label or slot position for two different
    containers, or multiple instruments assigned to the same axis.
    """


class ContainerConflict(ProtocolConflict):
    """
    Raised when a container is already allocated to a particular slot,
    or uses the same label.
    """


class InstrumentConflict(ProtocolConflict):
    """
    Raised when an instrument can't be placed in a particular axis because the
    desired axis is already in use.
    """


class ProtocolItemMissing(ProtocolException):
    """
    Raised when an element is missing from a Protocol, such as when a
    transfer references a container that doesn't exist.
    """


class InstrumentMissing(ProtocolItemMissing):
    """
    Raised when an instrument an indicated instrument does not exist, or when
    no instrument can be found to complete a particular task.
    """


class ContainerMissing(ProtocolItemMissing):
    """
    Raised when an indicated container does not exist in a Protocol.
    """


class TipMissing(ProtocolItemMissing):
    """
    Raised when no available tip can be found to attach to a particular
    pipette.
    """


class CommandMissing(ProtocolItemMissing):
    """
    Raised when a desired command is unavailable.
    """


class SlotMissing(ProtocolItemMissing):
    """
    Riased when a slot position isn't available on a container.
    """


class LiquidException(ProtocolException):
    """
    Raised when something is wrong with the volume designated in a transfer,
    either that the source well does not contain the requisite amount or when
    the destination will be overflowed by a transfer.
    """


class LiquidOverflow(LiquidException):
    """
    Raised when the volume to be transferred to a destination exceeds the
    maximum capacity of a well.
    """


class LiquidUnavailable(LiquidException):
    """
    Raised when the volume to be transferred does not exist or is
    insufficient.
    """


class LiquidMismatch(LiquidException):
    """
    Raised when the volume specified is of a different type than what is
    available in a particular container.
    """
