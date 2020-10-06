"""Support for sending data to an RRD database."""
from threading import Timer
import threading
import time
import logging
import os.path
import statistics

from homeassistant.const import CONF_NAME, CONF_PATH, EVENT_HOMEASSISTANT_START, EVENT_HOMEASSISTANT_STOP, EVENT_STATE_CHANGED
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
    CONF_XFF,
    DEFAULT_STEP,
    DOMAIN,
    RRD_DIR,
)
from .utils import rrd_scaled_duration, convert_to_seconds

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
                vol.Required(CONF_DBS): vol.All(cv.ensure_list, [DB_SCHEMA]),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

_LOGGER = logging.getLogger(__name__)

hassIsShuttingDown = False


def setup(hass, config):
    """Set up the RRD Recorder component."""
    _LOGGER.debug("Setup started")
    conf = config[DOMAIN]
    entities = {}  # Mapping and caching of entities <-> data sources

    # Create RRD files, if not exist yet.
    for database in conf[CONF_DBS]:
        datasources = []
        rras = []
        for ds in database[CONF_DS]:
            ds_string = f"DS:{ds[CONF_NAME]}:{ds[CONF_CF]}:{ds[CONF_HEARTBEAT]}:{ds.get(CONF_MIN, 'U')}:{ds.get(CONF_MAX, 'U')}"
            datasources.append(ds_string)
            entities[ds[CONF_SENSOR]] = ds[CONF_NAME], 0, None

        for rra in database[CONF_RRA]:
            # CONF_CF:
            # - AVERAGE: Average value for the step period.
            # - MIN: Min value for the step period.
            # - MAX: Max value for the step period.
            # - LAST: Last value for the step period which got inserted by the update script.
            # CONF_XFF: What percentage of UNKOWN data is allowed so that the consolidated value
            #           is still regarded as known: 0% - 99%. Typical is 50%. Value in range 0-1
            # CONF_STEPS: How many step values will be used to build a single archive entry.
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


    def update(database):
        step = convert_to_seconds(database[CONF_STEP])
        _LOGGER.debug("%s will be updated every %s seconds.", database[CONF_NAME] + ".rrd", step)

        rrd_filename = hass.config.path(rrd_dir, database[CONF_NAME]) + ".rrd"

        while not hassIsShuttingDown:
            # Wait for the begining of next `step` interval.
            now = time.time()
            nextSavingTimestamp = ((now // step) + 1) * step
            time.sleep(nextSavingTimestamp - now)

            if (hassIsShuttingDown):
                return


            # RRD data source names for store.
            ds_names = []
            # RRD data source values for store. Corresponding with `ds_names` variable.
            ds_values = []

            for data_source in database[CONF_DS]:
                sensor_id = data_source[CONF_SENSOR]
                ds_name = data_source[CONF_NAME]

                # Get data value
                sensor_state = hass.states.get(sensor_id)
                try:
                    if sensor_state is None:
                        _LOGGER.debug(
                            "[%s] Skipping sensor %s, because value is unknown.", rrd_filename, sensor_id
                        )
                        raise Exception("Sensor has no value or not exists.")

                    sensor_value = sensor_state.state
                    # Convert value to integer, when type is COUNTER or DERIVE.
                    if (data_source[CONF_CF] in ["COUNTER", "DERIVE"]):
                        sensor_value = round(float(sensor_value))
                except:
                    _LOGGER.debug(
                        "[%s] sensor %s value will be stored as NaN.", rrd_filename, sensor_id
                    )
                    sensor_value = "NaN"

                # Add pais of name+value. Will be used as parameters for data save to rrd file.
                ds_names.append(ds_name)
                ds_values.append(str(sensor_value))

                try:
                    template = ":".join(ds_names)
                    timestamp = int(time.time())
                    values_string = ":".join(ds_values)

                    rrdtool.update(
                        rrd_filename, f"-t{template}", f"{timestamp}:{values_string}"
                    )
                    _LOGGER.debug(
                        "%s data added. ds=%s, values=%s:%s", rrd_filename, template, timestamp, values_string
                    )
                except rrdtool.OperationalError as exc:
                    _LOGGER.error(exc)


    # Executed on Home assistant start
    def start(_):
        try:
            for database in conf[CONF_DBS]:
                # Run each database updating in own thread.
                th = threading.Thread(target=update, args=[database])
                th.daemon = True
                th.start()

        except exc:
            _LOGGER.error(exc)


    # Stop updating all RRD files.
    def stop(_):
       _LOGGER.debug("Stopping data updating")
       hassIsShuttingDown = True


    # Start to store data after app start
    hass.bus.listen_once(EVENT_HOMEASSISTANT_START, start)

    # Stop updating in all threads in case of Home Assistent shutting down
    hass.bus.listen_once(EVENT_HOMEASSISTANT_STOP, stop)

    _LOGGER.debug("Setup finished")

    return True
