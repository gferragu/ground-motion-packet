# stdlib imports
# third party imports
import json
import re
from datetime import datetime
from typing import List, Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel

# local imports
from gmpacket.feature import Feature
from gmpacket.provenance import Provenance
from gmpacket.utils import datetime_to_iso8601


# ######################################
# We're monkey-patching the json module to control the output precision of floats
class RoundingFloat(float):
    __repr__ = staticmethod(lambda x: format(x, ".5g"))


json.encoder.c_make_encoder = None
json.encoder.float = RoundingFloat
# ######################################


class Event(BaseModel):
    """Represent a ground motion packet Event object."""

    type: str = "Feature"
    properties: dict
    geometry: dict

    @classmethod
    def from_params(cls, id, time, magnitude, lat, lon, depth):
        props = {"id": id, "time": time, "magnitude": magnitude}
        geometry = {"type": "Point", "coordinates": [lon, lat, depth * 1000]}
        return cls(properties=props, geometry=geometry)

    class Config:
        json_encoders = {
            # custom output conversion for datetime
            datetime: datetime_to_iso8601
        }


class GroundMotionPacket(BaseModel):
    """Represent a high level ground motion packet object."""

    type = "FeatureCollection"
    version: str
    creation_time: datetime = datetime.utcnow()
    event: Optional[Event]
    provenance: Provenance
    features: List[Feature]

    class Config:
        anystr_strip_whitespace = True
        json_encoders = {
            # custom output conversion for datetime
            datetime: datetime_to_iso8601
        }

    @classmethod
    def load_from_json(cls, filename):
        with open(filename, "rt") as f:
            data = json.load(f)
        return cls(**data)

    def save_to_json(self, filename):
        json_str = self.as_json()
        with open(filename, "wt") as f:
            f.write(json_str)

    def as_dict(self):
        return self.dict(by_alias=True)

    def as_json(self):
        # pydantic doesn't seem to support minifying output, so we'll use a combination
        # of pydantic and json module methods to minify and get json encoding the way we want
        jdict = json.loads(self.json(by_alias=True))
        return json.dumps(jdict, separators=(",", ":"))

    def to_dataframe(self):
        """Render the groundmotion packet to a pandas dataframe object."""
        event_dict = self.event.properties.copy()
        cdict = dict(
            zip(
                ["event_longitude", "event_latitude", "event_depth"],
                self.event.geometry["coordinates"],
            )
        )
        event_dict.update(cdict)
        rows = []
        for feature in self.features:
            feature_row = {}
            feature_row.update(event_dict)
            feature_row["network"] = feature.properties.network_code
            feature_row["station"] = feature.properties.station_code
            feature_row["station_name"] = feature.properties.name
            (
                feature_row["station_longitude"],
                feature_row["station_latitude"],
                feature_row["station_elevation"],
            ) = feature.geometry.coordinates
            for stream in feature.properties.streams:
                for trace in stream.traces:
                    row = {}
                    row.update(feature_row)
                    row["component"] = trace.properties.channel_code
                    row["location"] = trace.properties.location_code
                    for metric in trace.metrics:
                        metric_type = metric.properties.name
                        metric_units = metric.properties.units
                        values = np.array(metric.values)
                        if metric.dimensions is None:  # scalar value
                            key = f"{metric_type}({metric_units})"
                            value = metric.values
                            row[key] = value
                        elif metric.dimensions.number == 2:
                            nrows, ncols = values.shape
                            key_template = f"{metric_type}({metric_units})_"
                            for irow in range(0, nrows):
                                row_name = re.sub(
                                    r"\s+", "_", metric.dimensions.names[0]
                                )
                                row_label = metric.dimensions.axis_values[0][irow]
                                row_unit = metric.dimensions.units[0]
                                for jcol in range(0, ncols):
                                    col_name = re.sub(
                                        r"\s+", "_", metric.dimensions.names[1]
                                    )
                                    col_label = metric.dimensions.axis_values[1][jcol]
                                    col_unit = metric.dimensions.units[1]
                                    key = (
                                        key_template
                                        + f"{row_name}_{row_label}{row_unit}_{col_name}_{col_label}{col_unit}"
                                    )
                                    value = values[irow, jcol]
                                    row[key] = value
                        elif metric.dimensions.number != 2:
                            raise Exception("Can't support 1d arrays yet!")
                    rows.append(row)

        dataframe = pd.DataFrame(rows)
        return dataframe