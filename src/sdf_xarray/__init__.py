from collections import defaultdict
import os
import pathlib

from . import sdf

import xarray as xr
from xarray.backends import BackendEntrypoint
from xarray.core.utils import try_read_magic_number_from_path


def open_sdf_dataset(filename_or_obj, *, drop_variables=None):
    if isinstance(filename_or_obj, pathlib.Path):
        # sdf library takes a filename only
        # TODO: work out if we need to deal with file handles
        filename_or_obj = str(filename_or_obj)

    data = sdf.read(filename_or_obj, dict=True)

    # Drop any requested variables
    if drop_variables:
        for variable in drop_variables:
            # TODO: nicer error handling
            data.pop(variable)

    # These two dicts are global metadata about the run or file
    attrs = {}
    attrs.update(data.pop("Header", {}))
    attrs.update(data.pop("Run_info", {}))

    data_vars = {}
    coords = {}

    # Read and convert SDF variables and meshes to xarray DataArrays and Coordinates
    for key, value in data.items():
        if key.startswith("CPU"):
            # Had some problems with these variables, so just ignore them for now
            continue

        if isinstance(value, sdf.BlockConstant):
            # This might have consequences when reading in multiple files?
            attrs[key] = value.data

        elif isinstance(value, sdf.BlockPlainMesh):
            # These are Coordinates

            # There may be multiple grids all with the same coordinate names, so
            # drop the "Grid/" from the start, and append the rest to the
            # dimension name. This lets us disambiguate them all. Probably
            base_name = key.split("/", maxsplit=1)[-1]

            for label, coord, unit in zip(value.labels, value.data, value.units):
                full_name = f"{label}_{base_name}"
                coords[full_name] = (
                    full_name,
                    coord,
                    {"long_name": label, "units": unit},
                )
        elif isinstance(value, sdf.BlockPlainVariable):
            # These are DataArrays

            # SDF makes matching up the coordinates a bit convoluted. Each
            # dimension on a variable can be defined either on "grid" or
            # "grid_mid", and the only way to tell which one is to compare the
            # variable's dimension sizes for each grid. We do this by making a
            # nested dict that looks something like:
            #
            #     {"X": {129: "X_Grid", 129: "X_Grid_mid"}}
            #
            # Then we can look up the dimension label and size to get *our* name
            # for the corresponding coordinate
            dim_size_lookup = defaultdict(dict)

            # TODO: remove duplication with coords branch
            grid_base_name = value.grid.name.split("/", maxsplit=1)[-1]
            for dim_size, dim_name in zip(value.grid.dims, value.grid.labels):
                dim_size_lookup[dim_name][dim_size] = f"{dim_name}_{grid_base_name}"

            grid_mid_base_name = value.grid_mid.name.split("/", maxsplit=1)[-1]
            for dim_size, dim_name in zip(value.grid_mid.dims, value.grid_mid.labels):
                dim_size_lookup[dim_name][dim_size] = f"{dim_name}_{grid_mid_base_name}"

            var_coords = (
                dim_size_lookup[dim_name][dim_size]
                for dim_name, dim_size in zip(value.grid.labels, value.dims)
            )
            # TODO: error handling here? other attributes?
            data_attrs = {"units": value.units}
            data_vars[key] = (var_coords, value.data, data_attrs)

    # TODO: might need to decode if mult is set?

    # #  see also conventions.decode_cf_variables
    # vars, attrs, coords = my_decode_variables(
    #     vars, attrs, decode_times, decode_timedelta, decode_coords
    # )

    ds = xr.Dataset(data_vars, attrs=attrs, coords=coords)
    # I think SDF basically keeps files open for the whole lifetime of the
    # Python block variables, so there's no way to explicitly close them
    ds.set_close(lambda: None)

    return ds


class SDFEntrypoint(BackendEntrypoint):
    def open_dataset(
        self,
        filename_or_obj,
        *,
        drop_variables=None,
    ):
        return open_sdf_dataset(filename_or_obj, drop_variables=drop_variables)

    open_dataset_parameters = ["filename_or_obj", "drop_variables"]

    def guess_can_open(self, filename_or_obj):
        magic_number = try_read_magic_number_from_path(filename_or_obj)
        if magic_number is not None:
            return magic_number.startswith(b"SDF1")

        try:
            _, ext = os.path.splitext(filename_or_obj)
        except TypeError:
            return False
        return ext in {".sdf", ".SDF"}

    description = "Use .sdf files in Xarray"

    url = "https://epochpic.github.io/documentation/visualising_output/python.html"
