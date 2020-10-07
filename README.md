# RRD Recorder for Home Assistant

This integration is similar to other recorders (e.g. influxdb) but uses [RRDTool](https://oss.oetiker.ch/rrdtool/) as a backend.
The main benefit of using RRD Recorder is that you can store data for long periods of time without the complexity of adding servers/addon's, unfortunantely it comes with the cost of loss of detailed information for older periods of time (the concept is that you don't need details to the second for data generated a year ago, the average of the day year ago is enough)

Currently this integration also records to the RRD database files. In the future I plan for a "Camera" platform that will generate the graphs

## Installation

RRD Recorder depends on librrd which is a C library. 

You will need to follow the steps in https://pythonhosted.org/rrdtool/install.html before this integration will work.

Most likely this will suffice in Debian/Ubuntu:
```bash
$ sudo apt-get install librrd-dev libpython3-dev
```

If you are using Alpine Linux (the base of many Docker Images):
```bash
$ apk add build-base rrdtool-dev python3-dev py-pip
```

## Configuration

Example:

```yaml
# Example configuration.yaml
rrd:
  path: '/rrd'
  databases:
    - name: internet_connection
      step: 30s
      data_sources:
        - sensor: sensor.upnp_router_bytes_received
          name: recv
          cf: COUNTER
          heartbeat: 300
        - sensor: sensor.upnp_router_bytes_sent
          name: sent
          cf: COUNTER
          heartbeat: 300
      round_robin_archives:
        - cf: AVERAGE
          steps: 1m
          rows: 1h
        - cf: AVERAGE
          steps: 5m
          rows: 1d
        - cf: AVERAGE
          steps: 1h
          rows: 1w
        - cf: AVERAGE
          steps: 1d
          rows: 12M

camera:
  - platform: rrd
    name: vodafone
    rrdfile: /rrd/mydata.rrd
    timerange: 2d  
    args:   #if you don't define any args you will get lines corresponding to the DS's in the file
      - "VDEF:vrecv=Recv,MAXIMUM"
      - "VRULE:vrecv#FF3300:MAX"
      - "VDEF:sent=Sent,MAXIMUM"
      - "VRULE:sent#000000:MAX"
      - "AREA:Recv#00FF00:Received Bytes"
      - "LINE1:Sent#0033FF:Sent Bytes"
```

### RRD Configuration

```yaml
path:
  description: The location relative to your HA config path where you want to store your rrd database files
  required: false
  type: string
databases:
  description: List of RRD databases (files) 
  required: true
  type: list
  keys:
    name:
      description: Name of the database
      required: true
      type: string
    step: 
      description: how often to expect updates
      required: false
      type: seconds
      default: 300
    data_sources:
      description: Data Sources (DS) of the database
      required: true
      type: list
      keys:
        sensor:
          description: entity id to keep record of
          required: true
          type: entity_id
        name:
          description: short name to be used internally by RRD
          required: true
        cf: 
          description: consolidation function (check https://oss.oetiker.ch/rrdtool/doc/rrdcreate.en.html) for available functions
          required: true
          type: list
        heartbeat:
          description: amount of time after which DS is considered unknown
    round_robin_archives:
      description: Round Robin Archives stored
      required: true
      type: list
      keys:
        cf: 
          description: consolidation function (check https://oss.oetiker.ch/rrdtool/doc/rrdcreate.en.html) for available functions. Possible values are 'MIN','MAX','AVERAGE','LAST'
          required: true
          type: list
        steps:
          description: periodicy of records (a record is stored every step)
          required: true
          type: seconds
        rows:
          description: amount of steps recorded in the database
          required: true
          type: int
```

### Camera configuration

The camera component tries to guess everything from the rrd file. But you can always pass new arguments in *args*.

**Hint** use a tool such as [http://rrdwizard.appspot.com/rrdgraph.php](http://rrdwizard.appspot.com/rrdgraph.php)
```yaml
name:
  description: Name of the camera entity 
  required: true
  type: string
rrdfile:
  description: path to the rrd file
  required: true
width:
  description: width of the generated graph
  required: false
  default: 400
height:
  description: height of the generated graph
  required: false
  default: 100
timerange:
  description: amount of time to be displayed
  required: false
  default: 1d
args:
  description: common arguments used by *rrdtool graph*
  required: false
```
