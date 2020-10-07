"""Constants for InfluxDB integration."""
from datetime import timedelta

DEFAULT_DATABASE = "home_assistant.rrd"
DOMAIN = "rrd"

DEFAULT_STEP = "5m"
RRD_DIR = "rrd"

CONF_DBS = "databases"
CONF_DS = "data_sources"
CONF_SENSOR = "sensor"
CONF_STEP = "step"
CONF_CF = "cf"
CONF_HEARTBEAT = "heartbeat"
CONF_MIN = "min"
CONF_MAX = "max"
CONF_RRA = "round_robin_archives"
CONF_XFF = "xff"
CONF_STEPS = "steps"
CONF_ROWS = "rows"

CONF_RRD_FILE = "rrdfile"
CONF_WIDTH = "width"
CONF_HEIGHT = "height"
CONF_TIMERANGE = "timerange"
CONF_ARGS = "args"
