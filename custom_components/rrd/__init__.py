"""Support for sending data to an RRD database."""
from datetime import datetime
import logging
import os.path
import statistics

from homeassistant.const import CONF_NAME, CONF_PATH, EVENT_STATE_CHANGED
from homeassistant.helpers import state as state_helper
import homeassistant.helpers.config_validation as cv
import rrdtool
import voluptuous as vol

from .const import (
    CONF_CF,
    CONF_DBS,
    CONF_DS,
    CONF_HEARTBEAT,
    CONF_MAX,
    CONF_MIN,
    CONF_ROWS,
    CONF_RRA,
    CONF_SENSOR,
    CONF_STEP,
    CONF_STEPS,
    CONF_TOLERANCE,
    CONF_XFF,
    DEFAULT_STEP,
    DOMAIN,
    RRD_DIR,
)
from .utils import rrd_scaled_duration

DS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SENSOR): cv.entity_id,
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_CF): vol.In(
            ["GAUGE", "COUNTER", "DERIVE", "DCOUNTER", "DDERIVE", "ABSOLUTE"]
        ),
        vol.Required(CONF_HEARTBEAT): rrd_scaled_duration,
        vol.Optional(CONF_MIN): cv.Number,
        vol.Optional(CONF_MAX): cv.Number,
    },
    extra=vol.ALLOW_EXTRA,
)

RRA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CF): vol.In(["AVERAGE", "MIN", "MAX", "LAST"]),
        vol.Optional(CONF_XFF, default=0.5): vol.Range(min=0, max=1),
        vol.Required(CONF_STEPS): rrd_scaled_duration,
        vol.Required(CONF_ROWS): rrd_scaled_duration,
    },
    extra=vol.ALLOW_EXTRA,
)

DB_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Optional(CONF_STEP, default=DEFAULT_STEP): rrd_scaled_duration,
        vol.Required(CONF_DS): vol.All(cv.ensure_list, [DS_SCHEMA]),
        vol.Required(CONF_RRA): vol.All(cv.ensure_list, [RRA_SCHEMA]),
    },
    extra=vol.ALLOW_EXTRA,
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_PATH, default=RRD_DIR): cv.string,
                vol.Optional(CONF_TOLERANCE, default=1): vol.Range(min=0),
                vol.Required(CONF_DBS): vol.All(cv.ensure_list, [DB_SCHEMA]),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

_LOGGER = logging.getLogger(__name__)


def setup(hass, config):
    """Set up the RRD Recorder component."""
    conf = config[DOMAIN]
    entities = {}  # Mapping and caching of entities <-> data sources

    for database in conf[CONF_DBS]:
        datasources = []
        rras = []
        for ds in database[CONF_DS]:  # pylint: disable=C0103
            ds_string = f"DS:{ds[CONF_NAME]}:{ds[CONF_CF]}:{ds[CONF_HEARTBEAT]}:{ds.get(CONF_MIN, 'U')}:{ds.get(CONF_MAX, 'U')}"
            datasources.append(ds_string)
            _LOGGER.debug(ds_string)
            entities[ds[CONF_SENSOR]] = ds[CONF_NAME], 0, None

        for rra in database[CONF_RRA]:
            rras.append(
                f"RRA:{rra[CONF_CF]}:{rra[CONF_XFF]}:{rra[CONF_STEPS]}:{rra[CONF_ROWS]}"
            )

        rrd_dir = conf[CONF_PATH]
        rrd_filename = hass.config.path(rrd_dir, database[CONF_NAME]) + ".rrd"

        try:
            if not os.path.exists(hass.config.path(rrd_dir)):
                _LOGGER.debug("Creating %s", hass.config.path(rrd_dir))
                os.makedirs(hass.config.path(rrd_dir))
            if not os.path.isfile(rrd_filename):
                # TODO: Make this a service to overwrite the file afterward only on request
                _LOGGER.debug("Creating file %s", rrd_filename)

                rrdtool.create(
                    rrd_filename,
                    "--start",
                    "now",
                    "--step",
                    database[CONF_STEP],
                    *rras,
                    *datasources,
                )
        except rrdtool.OperationalError as exc:
            _LOGGER.error(exc)
            return False

    def rrd_update(event):
        state = event.data.get("new_state")
        if state is None:
            return

        if state.entity_id not in entities:
            return

        _last_changed_ts = int(datetime.timestamp(state.last_changed))
        _state = int(state_helper.state_as_number(state))

        ds_name, _, _ = entities[state.entity_id]
        entities[state.entity_id] = ds_name, _last_changed_ts, _state

        entities_last_changed = [
            last_changed for _, last_changed, _ in entities.values()
        ]

        if (
            len(entities_last_changed) == 1
            or statistics.stdev(entities_last_changed) <= conf[CONF_TOLERANCE]
        ):  # all entities recently updated so lets store
            try:
                ds_names, values = zip(
                    *[(ds_name, value) for ds_name, _, value in entities.values()]
                )
                template = ":".join(ds_names)
                timestamp = int(max(entities_last_changed))
                values_string = ":".join([str(v) for v in values])

                rrdtool.update(
                    rrd_filename, f"-t{template}", f"{timestamp}:{values_string}"
                )
                _LOGGER.debug(
                    "[%s] %s %s:%s", rrd_filename, template, timestamp, values_string,
                )
            except rrdtool.OperationalError as exc:
                _LOGGER.error(exc)
        else:
            _LOGGER.debug("skipping <%s> until other DS update", ds_name)

    hass.bus.listen(EVENT_STATE_CHANGED, rrd_update)

    return True
