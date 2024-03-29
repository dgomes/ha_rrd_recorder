"""Provide a graph of an rrd database."""
import logging
import re

from homeassistant.components.camera import PLATFORM_SCHEMA, Camera
from homeassistant.const import CONF_NAME
from homeassistant.helpers import config_validation as cv
import rrdtool
import voluptuous as vol

from .const import CONF_ARGS, CONF_HEIGHT, CONF_RRD_FILE, CONF_TIMERANGE, CONF_WIDTH, CONF_RRDGRAPH_OPTIONS
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
            vol.Optional(CONF_RRDGRAPH_OPTIONS, default=[]): vol.All(cv.ensure_list, [cv.string]),
        }
    )
)


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up RRD Graph camera component."""
    name = config[CONF_NAME]

    _LOGGER.debug("Setup RRD Graph %s", name)
    add_entities([RRDGraph(config)], True)


class RRDGraph(Camera):
    """
    A camera component producing a graph of a RRD database.

    Full documentation about RRDgraph at https://oss.oetiker.ch/rrdtool/doc/rrdgraph.en.html
    """

    def __init__(self, config):
        """
        Initialize the component.

        This constructor must be run in the event loop.
        """
        super().__init__()

        self._name = config[CONF_NAME]
        rrd_file = config[CONF_RRD_FILE]

        self._config = config
        self._unique_id = f"rrd_{self._name}"

        color = iter(["#00FF00", "#0033FF"])
        self._defs = []
        self._lines = []
        try:
            rrdinfo = rrdtool.info(rrd_file)
            rra0_cf = rrdinfo[f"rra[0].cf"]
            self._step = rrdinfo["step"]
            for key in rrdinfo.keys():
                if ".index" in key:
                    ds = re.search(r"\[(.*?)\]", key).group(1)  # Datasource name
                    self._unique_id += f"_{ds}"

                    # Append DEF of primary DS RRA
                    graph_def = f"DEF:{ds.capitalize()}={rrd_file}:{ds}:{rra0_cf}"
                    self._defs.append(graph_def)
                    _LOGGER.debug('Added graph %s', graph_def)

                    # Append all other RRAs as DEF with names "{ds.capitalize()}_{rra_cf}_{rra_pdp_per_row}". Example "Temperature_AVERAGE_96".
                    rra_index = 1
                    while f"rra[{rra_index}].cf" in rrdinfo and f"rra[{rra_index}].pdp_per_row" in rrdinfo:
                        rra_pdp_per_row = rrdinfo[f"rra[{rra_index}].pdp_per_row"]
                        rra_cf = rrdinfo[f"rra[{rra_index}].cf"]
                        rra_step = rra_pdp_per_row * self._step
                        graph_def = f"DEF:{ds.capitalize()}_{rra_cf}_{rra_pdp_per_row}={rrd_file}:{ds}:{rra_cf}:step={rra_step}"
                        self._defs.append(graph_def)
                        _LOGGER.debug('Added graph %s', graph_def)
                        rra_index += 1


                    # Check if args already defines LINE or AREA for our DEF, this also means the user can overwrite it
                    if [] == [
                        True
                        for line in config[CONF_ARGS]
                        if ds.capitalize() in line
                        and ("LINE" in line or "AREA" in line or "CDEF" in line)
                    ]:
                        self._lines.append(
                            f"LINE1:{ds.capitalize()}{next(color)}:{ds.capitalize()}"
                        )
        except rrdtool.OperationalError as exc:
            _LOGGER.error(exc)
        self._unique_id += f"_{self._step}"

    def camera_image(self, width, height):
        """
        Return a still image response from the camera.

        This will run rrdtool graph to generate a temporary file which will be served by this method.
        """
        _LOGGER.debug("Get RRD camera image")

        if not width:
            width = self._config[CONF_WIDTH]
        if not height:
            height = self._config[CONF_HEIGHT]

        try:
            ret = rrdtool.graphv(
                "-",
                "--width",
                str(width),
                "--height",
                str(height),
                "--start",
                "-" + self._config[CONF_TIMERANGE],
                *self._config[CONF_RRDGRAPH_OPTIONS],
                *self._defs,
                *self._lines,
                *self._config[CONF_ARGS],
            )
            return ret["image"]
        except rrdtool.OperationalError as exc:
            _LOGGER.error(exc)
            return False

    @property
    def name(self) -> str:
        """Return the component name."""
        return f"rrd_{self._name}"

    @property
    def unique_id(self):
        """Return the unique id."""
        return self._unique_id

    @property
    def frame_interval(self) -> int:
        """No need to update between steps."""
        return self._step
