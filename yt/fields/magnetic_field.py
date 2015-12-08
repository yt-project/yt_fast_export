"""
Magnetic field ... er, fields.



"""

#-----------------------------------------------------------------------------
# Copyright (c) 2013, yt Development Team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file COPYING.txt, distributed with this software.
#-----------------------------------------------------------------------------

import numpy as np

from yt.units import dimensions
from yt.units.unit_object import Unit
from yt.utilities.physical_constants import mu_0

from yt.fields.derived_field import \
    ValidateParameter

from .field_plugin_registry import \
    register_field_plugin

from yt.utilities.math_utils import \
    get_sph_theta_component, \
    get_sph_phi_component

mag_factors = {dimensions.magnetic_field_cgs: 4.0*np.pi,
               dimensions.magnetic_field_mks: mu_0}

@register_field_plugin
def setup_magnetic_field_fields(registry, ftype = "gas", slice_info = None):
    unit_system = registry.ds.unit_system

    if (ftype,"magnetic_field_x") not in registry:
        return

    u = registry[ftype,"magnetic_field_x"].units

    def _magnetic_field_strength(field,data):
        B2 = (data[ftype,"magnetic_field_x"]**2 +
              data[ftype,"magnetic_field_y"]**2 +
              data[ftype,"magnetic_field_z"]**2)
        return np.sqrt(B2)
    registry.add_field((ftype,"magnetic_field_strength"),
                       function=_magnetic_field_strength,
                       units=u)

    def _magnetic_energy(field, data):
        B = data[ftype,"magnetic_field_strength"]
        return 0.5*B*B/mag_factors[B.units.dimensions]
    registry.add_field((ftype, "magnetic_energy"),
             function=_magnetic_energy,
             units=unit_system["pressure"])

    def _plasma_beta(field,data):
        return data[ftype,'pressure']/data[ftype,'magnetic_energy']
    registry.add_field((ftype, "plasma_beta"),
             function=_plasma_beta,
             units="")

    def _magnetic_pressure(field,data):
        return data[ftype,'magnetic_energy']
    registry.add_field((ftype, "magnetic_pressure"),
             function=_magnetic_pressure,
             units=unit_system["pressure"])

    def _magnetic_field_poloidal(field,data):
        normal = data.get_field_parameter("normal")
        d = data[ftype,'magnetic_field_x']
        Bfields = data.ds.arr(
                    [data[ftype,'magnetic_field_x'],
                     data[ftype,'magnetic_field_y'],
                     data[ftype,'magnetic_field_z']],
                     d.units)

        theta = data["index", 'spherical_theta']
        phi   = data["index", 'spherical_phi']

        return get_sph_theta_component(Bfields, theta, phi, normal)

    registry.add_field((ftype, "magnetic_field_poloidal"),
             function=_magnetic_field_poloidal,
             units=u, validators=[ValidateParameter("normal")])

    def _magnetic_field_toroidal(field,data):
        normal = data.get_field_parameter("normal")
        d = data[ftype,'magnetic_field_x']
        Bfields = data.ds.arr(
                    [data[ftype,'magnetic_field_x'],
                     data[ftype,'magnetic_field_y'],
                     data[ftype,'magnetic_field_z']],
                     d.units)
        
        phi = data["index", 'spherical_phi']
        return get_sph_phi_component(Bfields, phi, normal)

    registry.add_field((ftype, "magnetic_field_toroidal"),
             function=_magnetic_field_toroidal,
             units=u, validators=[ValidateParameter("normal")])

    def _alfven_speed(field,data):
        B = data[ftype,'magnetic_field_strength']
        return B/np.sqrt(mag_factors[B.units.dimensions]*data[ftype,'density'])
    registry.add_field((ftype, "alfven_speed"), function=_alfven_speed,
                       units=unit_system["velocity"])

    def _mach_alfven(field,data):
        return data[ftype,'velocity_magnitude']/data[ftype,'alfven_speed']
    registry.add_field((ftype, "mach_alfven"), function=_mach_alfven,
                       units="dimensionless")

def setup_magnetic_field_aliases(registry, ds_fields, ftype="gas"):
    unit_system = registry.ds.unit_system
    ds_fields = [(registry.ds.dataset_type, fd) for fd in ds_fields]
    from_units = Unit(registry[ds_fields[0]].units,
                      registry=registry.ds.unit_registry)
    if dimensions.current_mks in unit_system.base_units:
        to_units = unit_system["magnetic_field_mks"]
        equiv = "SI"
    else:
        to_units = unit_system["magnetic_field_cgs"]
        equiv = "CGS"
    if from_units.dimensions == to_units.dimensions:
        convert = lambda x: x.in_units(to_units)
    else:
        convert = lambda x: x.to_equivalent(to_units, equiv)
    def mag_field(ax, fd):
        def _mag_field(field, data):
            return convert(data[fd])
        return _mag_field
    for ax, fd in zip("xyz", ds_fields):
        registry.add_field((ftype,"magnetic_field_%s" % ax),
                           function=mag_field(fd),
                           units=unit_system[to_units.dimensions])