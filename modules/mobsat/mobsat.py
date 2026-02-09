import json
import time
import os
import asyncio
import math 

from skyfield.api import load, EarthSatellite, wgs84
from datetime import datetime, timezone

from kernel.management_layer import LOGGER, PROCESS, subprocess
from kernel.module import module
from kernel.nats import NATS

class mobsat(module):
    
    actual_time = time.time()
    
    def _do_init(self):
        general_settings_path = "kernel/.config/config.json"
        with open(general_settings_path, 'r') as f:
            tmp_gs = json.load(f)
            
        self.base_date = tmp_gs["timeinf"]["DATE"]
        # Extract base date (Unix epoch)
        # Create Skyfield timescale
        self.ts = load.timescale()

        dir_path = os.path.dirname(os.path.realpath(__file__))
        settings_path = os.path.join(dir_path, "settings.json")
        
        with open(settings_path, 'r') as f:
            self.settingss = json.load(f)
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
        timer = self.base_date + dif_time*5
        
        converted_time = self.convert_time_scale(timer)
        
        message_grafa = {}
        message_pose = {}
        message_vel = {}
        for sat_name in self.sattelite.keys():
            sat_position, sat_velocity, msg_grafana= self.get_position(sat_name, converted_time)
            
            message_grafa[sat_name] = list(msg_grafana)
            message_pose[sat_name] = sat_position.tolist()
            message_vel[sat_name] = sat_velocity.tolist()
                 
        
        #print(f"debug mobsat\n{message_pose}\n")
        message_grafana = {"grafana": message_grafa,
                            "timestamp": float(timer)}
        message_position = {"position": message_pose,
                            "timestamp": float(timer)}
        message_velocity = {"velocity": message_vel,
                            "timestamp": float(timer)}
        
        await NATS.send("mobsat.position", message_position)
        await NATS.send("mobsat.velocity", message_velocity)
        await NATS.send("mobsat.grafana", message_grafana)
        await asyncio.sleep(0.1)
        
    def parse_tle_file(self, filename: str, N: int):
        satellites = []

        with open(filename, "r") as f:
            lines = [line.rstrip() for line in f if line.strip()]

        # Each satellite = 3 consecutive lines
        for i in range(0, len(lines), 3):
            if len(satellites) >= N:
                break

            name = lines[i]
            tle1 = lines[i + 1]
            tle2 = lines[i + 2]

        return satellites

    def ecef_xyz_to_latlonalt(self, xyz_m):
        
        WGS84_A = 6378137.0                 # semi-major axis (m)
        WGS84_E2 = 6.69437999014e-3         # eccentricity squared
        """
        Converte ECEF XYZ (metros) para latitude, longitude e altitude (WGS84)

        Parâmetros:
            xyz_m : array-like [x, y, z] em metros

        Retorna:
            lat_deg, lon_deg, alt_m
        """
        x, y, z = xyz_m

        # Longitude
        lon = math.atan2(y, x)

        # Distância ao eixo Z
        p = math.sqrt(x*x + y*y)

        # Latitude inicial (geocêntrica)
        lat = math.atan2(z, p * (1 - WGS84_E2))

        # Iteração para latitude geodésica
        for _ in range(5):
            sin_lat = math.sin(lat)
            N = WGS84_A / math.sqrt(1 - WGS84_E2 * sin_lat * sin_lat)
            lat = math.atan2(z + WGS84_E2 * N * sin_lat, p)

        # Altitude
        sin_lat = math.sin(lat)
        N = WGS84_A / math.sqrt(1 - WGS84_E2 * sin_lat * sin_lat)
        alt = p / math.cos(lat) - N

        return [math.degrees(lat), math.degrees(lon), alt]
    
    def convert_time_scale(self, time):
            return self.ts.utc(datetime.fromtimestamp(time, tz = timezone.utc))
            
    def get_position(self, name, time):
        if name not in self.sattelite:
            raise ValueError(f"Satellite '{name}' not found.")
        
        sat = self.sattelite[name]
        auxlocsat = sat.at(time)
        posixyz = auxlocsat.xyz.m
        velo = auxlocsat.velocity.m_per_s
        msg_graf = self.ecef_xyz_to_latlonalt(posixyz)
        
        return posixyz, velo, msg_graf
        
if __name__ == "__main__":
    a = 2