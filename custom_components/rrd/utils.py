"""Helper RRDTool functions."""
import voluptuous as vol


def rrd_scaled_duration(duration):
    """Validate according to https://oss.oetiker.ch/rrdtool/doc/librrd.en.html#rrd_scaled_duration_(const_char_*_token,_unsigned_long_divisor,_unsigned_long_*_valuep)."""

    if isinstance(duration, int):
        # We assume duration is in seconds (RRD original behaviour)
        return duration

    scaling_factor = duration[-1]
    if scaling_factor not in ["s", "m", "h", "d", "w", "M", "y"]:
        raise vol.Invalid("Must use a scaling factor with your number")

    try:
        number = int(duration[0:-1])
        if number <= 0:
            raise vol.Invalid("Duration must be positive")
    except Exception:
        raise vol.Invalid("Duration must be a number.")

    return duration
