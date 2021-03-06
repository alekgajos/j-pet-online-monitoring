import logging
from threading import Thread
import datetime as dt
from datetime import datetime
import dateutil.parser as dp
from plot import plotMeteoStuff
from shellchecks import *
import time
import cherrypy
import signal
import socket
import sys
import os

import meteo
import plot

plots_path = 'plots/'
daq_path = '/data/DAQ/'

db_path = './conditions_db.sqlite'

update_time = 60 # seconds

# for connection to the meteo station
sock = socket.socket(socket.AF_INET, # Internet
                     socket.SOCK_DGRAM) # UDP
server_address = ("172.16.32.127", 5143)

# for writing to DB
meteo.initDB(db_path)

# init logging
# Create a custom logger
logger = logging.getLogger('web_monitoring')

log_file_name = 'conditions_monitoring_' + time.strftime('%d-%m-%Y_%H-%M') + '.log'
logging.basicConfig(filename=log_file_name, level=logging.DEBUG,
                    format = '%(asctime)s - [%(name)s] %(levelname)s: %(message)s',
                    datefmt = '%m/%d/%Y %I:%M:%S %p')

state = {
    "x" : 0,
    "meteo_data" : [],
    "meteo_time_offset" : 0, # in seconds
    "readout_time" : None
}


def readMeteoStation():
    try:
        sock.sendto("Q", server_address)
        data = sock.recv(1024) # buffer size is 1024 bytes
        logger.debug("Received data from meteo server: " + data.strip())
        return data
    except:
        logger.error("In connection to meteo station: " + str(sys.exc_info()[0]))

def checkMeteoStation(S):
    line = readMeteoStation()
    read_time = datetime.now()
    data = meteo.writeRecord(line, read_time, 'zyx')
    logger.debug("Written data to DB: " + str(data))
    # check time offset between meteo028 PC and server
    dt = dp.parse(data[0]) - read_time
    S["meteo_time_offset"] = dt.total_seconds()
    
def getDataForPlots(S):
    now = datetime.now()
    retro_shift = dt.timedelta(days=-1)
    S["meteo_data"] =  meteo.getRecordsSince(now + retro_shift)

def makePlots(S):
    plot.plotMeteoStuff(S["meteo_data"], plots_path)
    
checks = (
    checkMeteoStation,
    getDataForPlots,
    makePlots
)


class Root(object):
    
    def __init__(self):
        self.last_readout = 0
        self.recent_folder = ""
        self.recent_file = ""

    def loadStatus(self, current_time):
        if( abs(current_time - self.last_readout) < 120 ):
            #if last readout was closer than 120 s, do not read out again
            return self.last_readout
        # if last readout was older, read out all relavant parameters
        #
        file = getMeteoLogFile()
        plotMeteoStuff(file, plots_path)
        file.close()
        #
        self.recent_folder = getMostRecentFolder(daq_path, '????.??.??_????')
        self.recent_file = getMostRecentFile(self.recent_folder[1])
        self.last_readout = current_time
        return current_time

    @cherrypy.expose
    def index(self):

        global state

        if state["readout_time"] is not None:
            readout_time = state["readout_time"].strftime('%Y-%m-%d %H:%M:%S')
        else:
            readout_time = 'No readouts.'
            
        s = """
        <HTML>
        <HEAD>
        <TITLE>J-PET Monitoring</TITLE>
        <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate" />
        <meta http-equiv="Pragma" content="no-cache" />
        <meta http-equiv="Expires" content="0" />
        <meta http-equiv="refresh" content="%d">
        </HEAD>
        <BODY BGCOLOR="FFFFFF">
        <DIV><h2>Status at: %s (last readout time)</h2></DIV>
        <CENTER>
        <IMG SRC="./plots/temp.png" ALIGN="BOTTOM"> 
        <IMG SRC="./plots/pressure.png" ALIGN="BOTTOM"> 
        <IMG SRC="./plots/patm.png" ALIGN="BOTTOM"> 
        <IMG SRC="./plots/humidities.png" ALIGN="BOTTOM"> 
        </CENTER> 
        <DIV><h3>Time difference between server and meteo PC: %d seconds</h3></DIV>
        </BODY>
        </HTML>
        """ % (update_time,
               readout_time,
               state["meteo_time_offset"],)
           #     self.recent_folder[1],
           #     os.path.basename(self.recent_file[1]),
           #     str(int(current_time-self.recent_file[0]))
           # )


        # <DIV><h3>Most recent folder %s</h3></DIV>
        # <DIV><h3>Most recent HLD file %s</h3></DIV>
        # <DIV><h3>Last access %s seconds ago</h3></DIV>
           
        return s

if __name__ == '__main__':
    conf = {
        'global': {
            # Remove this to auto-reload code on change and output logs
            # directly to the console (dev mode).
#            'environment': 'production',
        },
        '/': {
            'tools.sessions.on': True,
            'tools.sessions.timeout': 60 * 10, # hours
        },
        '/plots': {
            "tools.staticdir.on": True,
            "tools.staticdir.dir": "plots",
            "tools.staticdir.index": 'index.html',
            "tools.staticdir.root": os.getcwd(),
        }
    }

    # Take care of signal handling

    def signal_handler(sig, frame):
        print('You pressed Ctrl+C!')
        logger.info("SIGINT received, cleaning up and exiting.")
        
        sock.close()

        cherrypy.engine.exit()
        
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    
    # Start the server with the above app and the above config.
    def thread1(threadname):
        cherrypy.tree.mount(Root(), '/', conf)        
        cherrypy.config.update({'server.socket_host': '0.0.0.0', })
        cherrypy.config.update({'server.socket_port': 8000, })
        cherrypy.config.update({'log.screen': False,
                                'log.access_file': '',
                                'log.error_file': ''})
        cherrypy.engine.start()
        cherrypy.engine.block()

    # thread of the HTTP server
    thread1 = Thread( target=thread1, args=("HTTP Server thread", ) )
    thread1.daemon = True

    thread1.start()

    # control event loop
    while True:
        state["x"] = state["x"] + 1
        for f in checks:
            f(state)
        state["readout_time"] = datetime.now()
        time.sleep(update_time)
