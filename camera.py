"""Provide a graph of an rrd database."""
import logging
import re

from homeassistant.components.camera import PLATFORM_SCHEMA, Camera
from homeassistant.const import CONF_NAME
from homeassistant.helpers import config_validation as cv
import rrdtool
import voluptuous as vol

from .const import CONF_ARGS, CONF_HEIGHT, CONF_RRD_FILE, CONF_TIMERANGE, CONF_WIDTH
from .utils import rrd_scaled_duration

_LOGGER = logging.getLogger(__name__)

# Maximum range according to docs
IMAGE_RANGE = vol.All(vol.Coerce(int), vol.Range(min=120, max=700))


PLATFORM_SCHEMA = vol.All(
    PLATFORM_SCHEMA.extend(
        {
            vol.Optional(CONF_NAME): cv.string,
            vol.Required(CONF_RRD_FILE): cv.isfile,
            vol.Optional(CONF_WIDTH, default=400): IMAGE_RANGE,
            vol.Optional(CONF_HEIGHT, default=120): IMAGE_RANGE,
            vol.Optional(CONF_TIMERANGE, default="1d"): rrd_scaled_duration,
            vol.Required(CONF_ARGS): vol.All(cv.ensure_list, [cv.string]),
        }
    )
)


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up RRD Graph camera component."""
    name = config[CONF_NAME]
    rrd = config[CONF_RRD_FILE]
    width = config[CONF_WIDTH]
    height = config[CONF_HEIGHT]
    timerange = config[CONF_TIMERANGE]
    args = config[CONF_ARGS]

    _LOGGER.debug("Setup RRD Graph %s", name)
    add_entities([RRDGraph(name, rrd, width, height, timerange, args)], True)


class RRDGraph(Camera):
    """
    A camera component producing a graph of a RRD database.

    Full documentation about RRDgraph at https://oss.oetiker.ch/rrdtool/doc/rrdgraph.en.html
    """

    def __init__(self, name, rrd, width, height, timerange, args):
        """
        Initialize the component.

        This constructor must be run in the event loop.
        """
        super().__init__()

        self._name = name
        self._rrd = rrd

        self._width = width
        self._height = height
        self._timerange = timerange
        self._args = args
        self._unique_id = f"{self._rrd}"  # TODO use also an md5sum of args

        color = iter(["#00FF00", "#0033FF"])
        self._defs = []
        self._lines = []
        try:
            info = rrdtool.info(self._rrd)
            self._step = info["step"]
            for key, value in info.items():
                if ".index" in key:
                    ds = re.search(r"\[(.*?)\]", key).group(1)
                    self._unique_id += f"_{ds}"
                    cf = info[f"rra[{value}].cf"]
                    self._defs.append(f"DEF:{ds.capitalize()}={self._rrd}:{ds}:{cf}")
                    # Check if args already defines LINE or AREA for our DEF, this also means the user can overwrite it
                    if [] == [
                        True
                        for line in args
                        if ds.capitalize() in line
                        and ("LINE" in line or "AREA" in line)
                    ]:
                        self._lines.append(
                            f"LINE1:{ds.capitalize()}{next(color)}:{ds.capitalize()}"
                        )
        except rrdtool.OperationalError as exc:
            _LOGGER.error(exc)
        self._unique_id += f"_{self._step}"

    def camera_image(self):
        """
        Return a still image response from the camera.

        This will run rrdtool graph to generate a temporary file which will be served by this method.
        """
        _LOGGER.debug("Get RRD camera image")

        try:
            ret = rrdtool.graphv(
                "-",
                "--width",
                str(self._width),
                "--height",
                str(self._height),
                "--start",
                "-" + self._timerange,
                *self._defs,
                *self._lines,
                *self._args,
            )

            return ret["image"]
        except rrdtool.OperationalError as exc:
            _LOGGER.error(exc)
            return False

    @property
    def name(self) -> str:
        """Return the component name."""
        return self._name

    @property
    def unique_id(self):
        """Return the unique id."""
        return self._unique_id

    @property
    def frame_interval(self) -> int:
        """No need to update between steps."""
        return self._step
