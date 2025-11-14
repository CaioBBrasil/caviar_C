import json
import time
import os
from skyfield.api import load, EarthSatellite, wgs84
from datetime import datetime, timezone

from kernel.management_layer import LOGGER, PROCESS, subprocess
from kernel.module import module
from kernel.nats import NATS

class mobsat(module):
    
    actual_time = time.time()
    
    def _do_init(self):
        dir_path = os.path.dirname(os.path.realpath(__file__))
        settings_path = os.path.join(dir_path, "settings.json")
        
        with open(settings_path, 'r') as f:
            self.settingss = json.load(f)
        
        # Extract base date (Unix epoch)
        self.base_date = self.settingss["DATE"]

        # Create Skyfield timescale
        self.ts = load.timescale()

        # Dictionary to store satellites
        self.sattelite = {}

        # Iterate through satellites in JSON
        for sat_key, sat_data in self.settingss["SAT"].items():
            name = sat_data["NAME"]
            tle = sat_data["TLE"]
            self.sattelite[name] = EarthSatellite(
                tle["line1"],
                tle["line2"],
                name,
                self.ts
            )
        

    
    async def _execute_step(self):        
        dif_time = time.time() - self.actual_time
        timer = self.base_date + dif_time
        converted_time = self.convert_time_scale(timer)
        self.actual_time = time.time()
        message = {}
        for sat_name in self.sattelite.keys():
            sat_position, sat_velocity = self.get_position(sat_name, converted_time)
            
            message[sat_name] = {"Position": sat_position.tolist(), "velocity": sat_velocity.tolist() }
        message["timestamp"] = float(timer)
        
        #print(f"debug mobsat\n{message}\n")
        
        await NATS.send(self.__class__.__name__, message, "mobsat")
        
    
    def convert_time_scale(self, time):
            return self.ts.utc(datetime.fromtimestamp(time, tz = timezone.utc))
            
    def get_position(self, name, time):
        if name not in self.sattelite:
            raise ValueError(f"Satellite '{name}' not found.")
        
        sat = self.sattelite[name]
        auxlocsat = sat.at(time)
        posixyz = auxlocsat.xyz.km
        velo = auxlocsat.velocity.km_per_s
        return posixyz, velo
        
if __name__ == "__main__":
    a = 2