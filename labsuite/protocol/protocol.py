from labsuite.labware import containers, deck, pipettes
from labsuite.labware.grid import normalize_position, humanize_position
import labsuite.drivers.motor as motor_drivers
from labsuite.util.log import debug
from labsuite.protocol.handlers import ContextHandler, MotorControlHandler, RequirementsHandler
from labsuite.util import hashing
from labsuite.util import exceptions as x
from labsuite.util import ExceptionProxy

import time
import copy
import logging
import inspect

class Protocol():

    # Operational data.
    _ingredients = None  # { 'name': "A1:A1" }
    _head = None  # Head layout. { motor_axis: instrument name }
    _calibration = None  # Axis and instrument calibration.
    _container_labels = None  # Aliases. { 'foo': (0,0), 'bar': (0,1) }
    _label_case = None  # Capitalized labels.
    _containers = None  # { slot: container_name }
    _commands = None  # []

    # Metadata
    _name = None
    _description = None
    _created = None
    _updated = None
    _author = None
    _version = (0, 0, 0)
    _version_hash = None  # Only saved when the version is updated.

    # Context and Motor are important handlers, so we provide
    # a way to get at them.
    _handlers = None  # List of attached handlers for run_next.
    _context_handler = None  # Operational context (virtual robot).
    _motor_handler = None

    _partial_proxy = None  # PartialProtocol wrapping as a proxy.

    def __init__(self):
        self._ingredients = {}
        self._container_labels = {}
        self._label_case = {}
        self._head = {}
        self._calibration = {}
        self._containers = {}
        self._commands = []
        self._handlers = []
        self._context_handler = self.initialize_context()

    def set_info(self, name=None, description=None, created=None,
                 updated=None, author=None, version=None, **kwargs):
        """
        Sets the information metatadata of the protocol.
        """
        if name is not None:
            self._name = name
        if description is not None:
            self._description = description
        if author is not None:
            self._author = author
        if created is not None:
            self._created = created
        if updated is not None:
            self._updated = updated
        if version is not None:
            self._version = tuple(map(int, version.split('.')))
            self._version_hash = self.hash

    @property
    def info(self):
        """
        Returns information metatadata of the protocol (author, name,
        description, etc).
        """
        o = {}
        if self._name is not None:
            o['name'] = self._name
        if self._author is not None:
            o['author'] = self._author
        if self._description is not None:
            o['description'] = self._description
        o['created'] = self._created or str(time.strftime("%c"))
        o['updated'] = self._updated or str(time.strftime("%c"))
        o['version'] = self.version
        o['version_hash'] = self.hash
        return o

    @property
    def commands(self):
        return copy.deepcopy(self._commands)

    @property
    def instruments(self):
        return copy.deepcopy(self._head)

    @property
    def version(self):
        return ".".join(map(str, self._version))

    def bump_version(self, impact="minor"):
        vhash = self.hash
        if vhash == self._version_hash:
            # Don't bump the version if it's the same.
            return self.version
        major, feature, minor = self._version
        if impact == "minor":
            minor += 1
        elif impact == "feature":
            minor = 0
            feature += 1
        elif impact == "major":
            minor = 0
            feature = 0
            major += 1
        else:
            raise ValueError(
                "Impact must be one of: minor, feature, major."
            )
        self._version = (major, feature, minor)
        self._version_hash = vhash
        return self.version

    @property
    def hash(self):
        return hashing.hash_data([
            self._ingredients,
            self._head,
            self._container_labels,
            self._label_case,
            self._containers,
            self._commands
        ])

    def __eq__(self, protocol):
        return self.hash == protocol.hash

    def __add__(self, b):
        """
        Combines one Protocol with another, attempting to combine instrument
        and labware definitions as cleanly as possible.

        Returns a newly instantiated Protocol instance.

        If the Protocols are incompatible, it will raise a ProtocolConfict.
        """
        if isinstance(b, PartialProtocol):
            c = Protocol()
            c.apply_protocol(self)
            b.reapply(c)
            return c
        elif isinstance(b, type(self)):
            c = Protocol()
            c.apply_protocol(self)
            c.apply_protocol(b)
            return c
        else:
            raise TypeError("Invalid operand types for Protocol.")

    def apply_protocol(self, b):
        """
        Applies all the operational data from another Protocol to this one.
        """
        # Second info supercedes first.
        self.set_info(**b.info)
        # Add the containers from second.
        for slot, name in b._containers.items():
            if slot in self._containers and self._containers[slot] != name:
                raise x.ContainerConflict(
                    "Slot {} already allocated to {}".format(slot, name)
                )
            if slot not in self._containers:
                # Add container if it's not there already.
                self.add_container(slot, name)
        # Add the labels from second.
        labels = {v: k for k, v in self._container_labels.items()}
        for label, slot in b._container_labels.items():
            if slot in labels and labels[slot] != label:
                raise x.ContainerConflict(
                    "Conflicting labels at {}: {} vs {}"
                    .format(
                        humanize_position(slot),
                        labels[slot],
                        label
                    )
                )
            self._container_labels[label] = slot
        # Supercede labelcase from second.
        for label, case in b._label_case.items():
            self._label_case[label] = case
        # Add the instruments from second.
        for axis, name in b._head.items():
            if axis in self._head \
               and self._head[axis] != name:
                raise x.InstrumentConflict(
                    "Axis {} already allocated to {}".format(axis, name)
                )
            self.add_instrument(axis, name)
        # Rerun command definitions from second.
        for command in b.actions:
            c = copy.deepcopy(command)
            # Make sure this command runs properly.
            self.add_command(c.pop('command'), **c)
            self.commands.append(command)

    def add_container(self, slot, name, label=None):
        slot = normalize_position(slot)
        if (label):
            lowlabel = label.lower()
            if lowlabel in self._container_labels:
                raise x.ContainerConflict(
                    "Label already in use: {}".format(label)
                )
            # Maintain label capitalization, but only one form.
            if lowlabel not in self._label_case:
                self._label_case[lowlabel] = label
            self._container_labels[lowlabel] = slot
        self._context_handler.add_container(slot, name)
        self._containers[slot] = name

    def add_instrument(self, axis, name):
        self._head[axis] = name
        self._context_handler.add_instrument(axis, name)

    def calibrate(self, position, **kwargs):
        if ':' in position:
            pos = self._normalize_address(position)
        else:
            pos = normalize_position(position)
        self._context_handler.calibrate(pos, **kwargs)

    def calibrate_instrument(self, axis, top=None, blowout=None, droptip=None,
                             bottom=None):
        self._context_handler.calibrate_instrument(
            axis, top=top, blowout=blowout, droptip=droptip
        )

    def add_command(self, command, **kwargs):
        self._run_in_context_handler(command, **kwargs)
        d = {'command': command}
        d.update(**kwargs)
        self._commands.append(d)

    def transfer(self, start, end, ul=None, ml=None,
                 blowout=True, touchtip=True, tool=None):
        volume = self._normalize_volume(ul, ml)
        tool = self.get_tool(has_volume=volume, name=tool)
        self.add_command(
            'transfer',
            volume=volume,
            tool=tool.name,
            start=self._normalize_address(start),
            end=self._normalize_address(end),
            blowout=blowout,
            touchtip=touchtip
        )

    def transfer_group(self, *wells, tool=None, **defaults):
        transfers, min_vol, max_vol = self._make_transfer_group(
            wells, ['start', 'end'], defaults
        )
        tool = self.get_tool(
            name=tool, has_volumes=(min_vol, max_vol)
        )
        self.add_command(
            'transfer_group',
            tool=tool.name,
            transfers=transfers
        )

    def distribute(self, start, *wells, tool=None, **defaults):
        transfers, min_vol, max_vol = self._make_transfer_group(
            wells, ['end'], defaults
        )
        tool = self.get_tool(
            name=tool, has_volumes=(min_vol, max_vol)
        )
        self.add_command(
            'distribute',
            tool=tool.name,
            start=self._normalize_address(start),
            transfers=transfers
        )

    def consolidate(self, end, *wells, tool=None, **defaults):
        transfers, min_vol, max_vol = self._make_transfer_group(
            wells, ['start'], defaults
        )
        tool = self.get_tool(name=tool, has_volumes=(min_vol, max_vol))
        self.add_command(
            'consolidate',
            tool=tool.name,
            end=self._normalize_address(end),
            transfers=transfers
        )

    def mix(self, start, ml=None, ul=None, repetitions=None, tool=None,
            blowout=True, touchtip=True):
        volume = self._normalize_volume(ul, ml)
        tool = self.get_tool(name=tool, has_volume=volume)
        self.add_command(
            'mix',
            tool=tool.name,
            start=self._normalize_address(start),
            blowout=blowout,
            touchtip=touchtip,
            volume=volume,
            reps=repetitions
        )

    def _make_transfer_group(self, wells, arg_names, defaults):
        vols = []
        transfers = []
        volume = self._normalize_volume(
            defaults.pop('ul', None),
            defaults.pop('ml', None),
            skip_raise=True
        )
        vols = []
        for item in wells:
            # If it's not a tuple, there's only one arg and it has no options.
            if type(item) == tuple:
                item = list(item)
            else:
                item = [item]
            options = {
                'blowout': defaults.pop('blowout', True),
                'touchtip': defaults.pop('touchtip', True)
            }
            options.update(defaults)
            t = {}
            # Grab each argument from the argument tuple.
            for arg_name in arg_names:
                if len(item) == 0:
                    raise ValueError("Missing argument: {}".format(arg_name))
                v = item.pop(0)
                if arg_name in ['start', 'end']:
                    v = self._normalize_address(v)
                t[arg_name] = v
            if len(item) == 1:
                options.update(item.pop(0))
            vol = self._normalize_volume(
                options.pop('ul', None),
                options.pop('ml', None),
                volume
            )
            t['volume'] = vol
            t.update(options)
            transfers.append(t)
            vols.append(vol)
        return transfers, min(vols), max(vols)

    @property
    def actions(self):
        return copy.deepcopy(self._commands)

    def _get_slot(self, name):
        """
        Returns a container within a given slot, can take a slot position
        as a tuple (0, 0) or as a user-friendly name ('A1') or as a label
        ('ingredients').
        """
        slot = None

        try:
            slot = normalize_position(name)
        except TypeError:
            # Try to find the slot as a label.
            if slot in self._container_labels:
                slot = self._container_labels[slot]

        if not slot:
            raise x.MissingContainer("No slot defined for {}".format(name))
        if slot not in self._deck:
            raise x.MissingContainer("Nothing in slot: {}".format(name))

        return self._deck[slot]

    def _normalize_volume(self, ul, ml, default=None, skip_raise=False):
        if ul is 0 or ml is 0 or default is 0:
            raise ValueError("Volume must exceed 0.")
        if (ul and ml) and ml * 1000 != ul:
            raise ValueError("Conflicting volumes for ml and ul.")
        if ul:
            return ul
        if ml:
            return ml * 1000
        if default:
            return default
        if skip_raise is False:
            raise ValueError("No volume provided.")

    def _normalize_address(self, address):
        """
        Takes an address like "A1:A1" or "Ingredients:A1" and returns a tuple
        like ((0, 0), (0, 0)).

        To retain label names, use humanize_address.
        """

        if ':' not in address:
            raise ValueError(
                "Address must be in the form of 'container:well'."
            )

        container, well = address.split(':')
        well = normalize_position(well)

        try:
            container = normalize_position(container)
        except ValueError:
            # Try to find the slot as a label.
            container = container.lower()
            if container not in self._container_labels:
                raise x.ContainerMissing(
                    "Container not found: {}".format(address)
                )
            container = self._container_labels[container]

        return (container, well)

    def humanize_address(self, address):
        """
        Returns a human-readable string for a particular address.

        If ((0, 0), (1, 0)) is passed and no labels are attached to
        A1, this will return 'A1:B1'.

        For ('label', (1, 0)), it will return the valid label with
        the first provided capitalization, for example "LaBeL:B1".
        """
        start, end = address
        try:
            start = normalize_position(start)  # Try to convert 'A1'.
            # Find a label for that tuple position.
            label = self.get_container_label(start)
            if label is not None:
                start = label
        except ValueError:
            # If it's not a tuple position, it's a string label.
            if start.lower() not in self._container_labels:
                raise x.ContainerMissing(
                    "Invalid container: {}".format(start)
                )
            start = self._label_case.get(start.lower(), start)
        end = humanize_position(end)
        return "{}:{}".format(start, end)

    def get_container_label(self, position):
        for label, pos in self._container_labels.items():
            if pos == position:
                return self._label_case[label]
        return None

    def get_tool(self, **kwargs):
        tool = self._context_handler.get_instrument(**kwargs)
        if tool is None:
            raise x.InstrumentMissing(
                "No instrument found with parameters: {}"
                .format({k: v for k, v in kwargs.items() if v is not None})
            )
        return tool

    def run(self):
        """
        A generator that runs each command and yields the current command
        index and the number of total commands.
        """
        self.validate("Can't run an incomplete PartialProtocol.")
        # Reset our local context.
        self._context_handler = self.initialize_context()
        for h in self._handlers:
            h.set_context(self._context_handler)
        i = 0
        yield(0, len(self._commands))
        while i < len(self._commands):
            self._run(i)
            i += 1
            yield (i, len(self._commands))

    def run_all(self):
        """
        Convenience method to run every command in a protocol.

        Useful for when you don't care about the progress.
        """
        for _ in self.run():
            pass

    def initialize_context(self):
        """
        Initializes the context.
        """
        ch = ContextHandler(self)
        # Containers
        for slot, name in self._containers.items():
            ch.add_container(slot, name)
        # Instruments
        for axis, name in self._head.items():
            ch.add_instrument(axis, name)
        return ch

    def _run_in_context_handler(self, command, **kwargs):
        """
        Runs a command in the virtualized context.

        This is useful for letting us know if there's a problem with a
        particular command without having to wait to run it on the robot.

        If you use this on your own you're going to end up with weird state
        bugs that have nothing to do with the protocol.
        """
        method = getattr(self._context_handler, command)
        if not method:
            raise x.MissingCommand("Command not defined: " + command)
        method(**kwargs)

    def _run(self, index):
        kwargs = copy.deepcopy(self._commands[index])
        command = kwargs.pop('command')
        self._run_in_context_handler(command, **kwargs)
        for h in self._handlers:
            debug(
                "Protocol",
                "{}.{}: {}"
                .format(type(h).__name__, command, kwargs)
            )
            h.before_each()
            method = getattr(h, command)
            method(**kwargs)
            h.after_each()

    def _virtual_run(self):
        """
        Runs protocol on a virtualized MotorHandler to ensure that there are
        no run-specific problems.
        """
        old_motor = self._motor_handler
        if old_motor:
            self._handlers.remove(old_motor)
        new_motor = self.attach_motor()
        self._handler_runthrough(new_motor)
        if old_motor:
            self._motor_handler = old_motor
        logger.disabled = False

    def _handler_runthrough(self, handler):
        """
        Runs protocol on a virtualized handler.
        """
        # Disable logger.
        logger = logging.getLogger()
        logger.disabled = True
        # Disable the other handlers.
        old_handlers = self._handlers
        self._handlers = []
        try:
            handler = self.attach_handler(handler)
            self.run_all()
        finally:
            # Put everything back the way it was.
            logger.disabled = False
            self._handlers = old_handlers
        return handler

    def attach_handler(self, handler):
        """
        When you attach a handler, commands are run on the handler in sequence
        when Protocol.run_next() is called.

        You don't have to attach the ContextHandler, you get that for free.
        It's a good example implementation of what these things are
        supposed to do.

        Any command that the robot supports must be present on the Handler
        you pass in, or you'll get exceptions. Just make sure you subclass
        from ProtocolHandler and you'll be fine; empty methods are stubbed
        out for all supported commands.
        """
        if inspect.isclass(handler):
            handler = handler(self)
        handler.set_context(self._context_handler)
        handler.setup()
        self._handlers.append(handler)
        return handler

    def export(self, Formatter, validate_run=False, **kwargs):
        """
        Takes a ProtocolFormatter class (see protocol.formats), initializes
        it with any relevant options kwargs, passes in the current protocol,
        and outputs the data appropriate to the specific format.

        If validate_run is set to True, the protocol will be run on a
        virtual robot to catch any runtime errors (ie, no tipracks or
        trash assigned).
        """
        self.validate("Can't export invalid PartialProtocol.")
        self.bump_version()  # Bump if it hasn't happened manually.
        if validate_run:
            self._virtual_run()
        f = Formatter(self, **kwargs)
        return f.export()

    def attach_motor(self, port=None):
        self._motor_handler = self.attach_handler(MotorControlHandler)
        if port is not None:
            self._motor_handler.connect(port)
        else:
            self._motor_handler.simulate()
        return self._motor_handler

    def disconnect(self):
        if self._motor_handler:
            self._motor_handler.disconnect()

    def validate(self, error_message="Invalid Partial Protocol"):
        """
        Determines whether or not this Protocol is valid.
        """
        if self._partial_proxy is not None and \
           self._partial_proxy.is_valid is False:
            raise x.PartialProtocolException(
                error_message + " Problems: {}"
                .format("; ".join(self._partial_proxy.problems))
            )

    @classmethod
    def partial(self, *args, **kwargs):
        """
        Returns a Partial Protocol which can be appended to a full Protocol,
        allowing ProtocolExceptions within the partial to be ignored until
        final construction.
        """
        return PartialProtocol(Protocol(*args, **kwargs), x.ProtocolException)

    @property
    def run_requirements(self):
        req_handler = self._handler_runthrough(RequirementsHandler)
        return req_handler.requirements


class PartialProtocol(ExceptionProxy):
    pass
