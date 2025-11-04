import numpy as np
from skyfield.api import load, EarthSatellite, wgs84
import plotly.graph_objects as go
from math import sin, cos, atan2, sqrt, radians, degrees
from doa import rectangular_array, steering_vector

# ===============================================================
# Utility Functions
# ===============================================================

def latlon_from_ecef(r: np.ndarray):
    """Compute geocentric latitude and longitude from ECEF position vector."""
    x, y, z = r
    lon = atan2(y, x)
    hyp = sqrt(x ** 2 + y ** 2)
    lat = atan2(z, hyp)
    return lat, lon


def rotation_matrix_pointing_zenith_from_latlon(lat_deg: float, lon_deg: float) -> np.ndarray:
    """Return rotation matrix (ECEF → local) with +Z = zenith, +X = north, +Y = east."""
    lat, lon = radians(lat_deg), radians(lon_deg)

    up = np.array([cos(lat) * cos(lon), cos(lat) * sin(lon), sin(lat)])
    north = np.array([-sin(lat) * cos(lon), -sin(lat) * sin(lon), cos(lat)])
    east = np.array([-sin(lon), cos(lon), 0.0])

    # Normalize
    up /= np.linalg.norm(up)
    north /= np.linalg.norm(north)
    east /= np.linalg.norm(east)

    # Columns are body axes in ECEF
    return np.column_stack((north, east, up)).T


def rotation_matrix_pointing_zenith_from_ecef(r: np.ndarray) -> np.ndarray:
    """Return rotation matrix from ECEF position vector."""
    lat, lon = latlon_from_ecef(r)
    return rotation_matrix_pointing_zenith_from_latlon(degrees(lat), degrees(lon))


def rotation_matrix_pointing_nadir(sat_pos: np.ndarray) -> np.ndarray:
    """Compute rotation matrix for satellite pointing to Earth's center (nadir)."""
    r_hat = sat_pos / np.linalg.norm(sat_pos)
    z_body = -r_hat  # +Z points to Earth center
    ref_up = np.array([0, 0, 1])

    # Handle near-polar case
    if abs(np.dot(ref_up, z_body)) > 0.99:
        ref_up = np.array([0, 1, 0])

    x_body = np.cross(ref_up, z_body)
    x_body /= np.linalg.norm(x_body)
    y_body = np.cross(z_body, x_body)
    y_body /= np.linalg.norm(y_body)

    return np.column_stack((x_body, y_body, z_body)).T


# ===============================================================
# Core Classes
# ===============================================================

class Node:
    """Generic node (satellite or UE) with antenna array and steering vector."""

    def __init__(self, identify: str, posi: np.ndarray, array_geometry: np.ndarray, theta: float, phi: float):
        self.identify = identify
        self.position = np.array(posi)
        self.geometry = array_geometry
        self.array_posi = array_geometry + self.position
        self.steering_vec = steering_vector(array_geometry, theta, phi)

    def plot(self):
        """Plot antenna geometry."""
        coords = self.array_posi
        fig = go.Figure(
            data=[go.Scatter3d(
                x=coords[:, 0],
                y=coords[:, 1],
                z=coords[:, 2],
                mode='markers',
                marker=dict(size=5, color='red', opacity=0.8, symbol='circle')
            )]
        )
        fig.update_layout(
            title=f"Antenna Array of {self.identify}",
            scene=dict(
                xaxis_title="x (λ)",
                yaxis_title="y (λ)",
                zaxis_title="z (λ)",
                aspectmode="data"
            )
        )
        fig.show()


class Canvas:
    """3D visualization of Earth, satellites, and UEs."""

    def __init__(self, ues: dict, sats: dict, earth_radius_km: float = 6371):
        self.Earth = self._generate_earth_surface(earth_radius_km)
        self.satellites = sats
        self.UEs = ues

    @staticmethod
    def _generate_earth_surface(radius: float):
        """Generate a spherical mesh for the Earth."""
        theta, phi = np.linspace(0, np.pi, 40), np.linspace(0, 2 * np.pi, 40)
        theta, phi = np.meshgrid(theta, phi)
        x = radius * np.sin(theta) * np.cos(phi)
        y = radius * np.sin(theta) * np.sin(phi)
        z = radius * np.cos(theta)
        return np.array([x, y, z])

    def plot(self):
        """Plot Earth, satellites, and UEs."""
        X, Y, Z = self.Earth

        fig = go.Figure(data=[
            go.Surface(
                x=X, y=Y, z=Z,
                colorscale=[[0, 'blue'], [1, 'blue']],
                opacity=0.5, showscale=False,
                name="Earth"
            )
        ])

        # Satellites
        for sat in self.satellites.values():
            fig.add_trace(go.Scatter3d(
                x=[sat.position[0]],
                y=[sat.position[1]],
                z=[sat.position[2]],
                mode='markers',
                marker=dict(size=6, color='red'),
                name=f"Satellite {sat.identify}"
            ))

        # UEs
        for ue in self.UEs.values():
            fig.add_trace(go.Scatter3d(
                x=[ue.position[0]],
                y=[ue.position[1]],
                z=[ue.position[2]],
                mode='markers',
                marker=dict(size=6, color='green'),
                name=f"UE {ue.identify}"
            ))

        lim = [-1e4, 1e4]
        fig.update_layout(
            scene=dict(
                xaxis=dict(range=lim, title='X [km]'),
                yaxis=dict(range=lim, title='Y [km]'),
                zaxis=dict(range=lim, title='Z [km]'),
                aspectmode='cube'
            ),
            width=900,
            height=900,
            title="Earth, Satellites, and UEs"
        )
        fig.show()


# ===============================================================
# Example Execution
# ===============================================================

if __name__ == "__main__":
    ts = load.timescale()

    # ---- Satellite ----
    line1 = '1 25544U 98067A   14020.93268519  .00009878  00000-0  18200-3 0  5082'
    line2 = '2 25544  51.6498 109.4756 0003572  55.9686 274.8005 15.49815350868473'
    satellite = EarthSatellite(line1, line2, 'ISS (ZARYA)', ts)

    t = ts.utc(2014, 1, 23, 11, 18, 7)
    sat_pos = np.array(satellite.at(t).xyz.km)
    R_sat = rotation_matrix_pointing_nadir(sat_pos)

    array_params = dict(Mx=4, My=4, dx=0.25, dy=0.25, wavelength=1.0, origin=[0, 0, 0], rotation=R_sat)
    ar_geom_sat = rectangular_array(**array_params)
    node_sat1 = Node("Sat1", sat_pos, ar_geom_sat, 0, 0)
    node_sat1.plot()
    #-----------------------
    t = ts.utc(2014, 1, 23, 11, 20, 7)
    sat_pos = np.array(satellite.at(t).xyz.km)
    R_sat = rotation_matrix_pointing_nadir(sat_pos)

    array_params = dict(Mx=4, My=4, dx=0.25, dy=0.25, wavelength=1.0, origin=[0, 0, 0], rotation=R_sat)
    ar_geom_sat = rectangular_array(**array_params)
    node_sat2 = Node("Sat2", sat_pos, ar_geom_sat, 0, 0)
    node_sat2.plot()
    
    
    sats = {node_sat1.identify: node_sat1,
            node_sat2.identify: node_sat2}


    # ---- User Equipment ----
    bluffton = wgs84.latlon(+40.8939, -83.8917)
    ue_pos = np.array(bluffton.at(t).xyz.km)
    R_ue = rotation_matrix_pointing_zenith_from_ecef(ue_pos)

    array_params["rotation"] = R_ue
    ar_geom_ue = rectangular_array(**array_params)
    node_ue = Node("UE1", ue_pos, ar_geom_ue, 0, 0)
    node_ue.plot()
    ues = {node_ue.identify: node_ue}

    # ---- Visualization ----
    canvas = Canvas(ues, sats)
    canvas.plot()
